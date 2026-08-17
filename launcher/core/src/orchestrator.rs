use std::thread;
use std::time::Instant;

use crate::config::LauncherConfig;
use crate::download::Downloader;
use crate::health::{HealthClient, HealthStatus};
use crate::runner::CommandRunner;
use crate::state::LauncherState;

/// Runs `docker info` to check the container runtime is installed and its daemon reachable.
/// Returns `Err(detail)` with a message meant to be shown directly to a non-technical operator
/// (Error Visibility acceptance criterion).
fn docker_daemon_available(runner: &dyn CommandRunner, cfg: &LauncherConfig) -> Result<(), String> {
    match runner.run("docker", &["info"], &cfg.project_dir) {
        Ok(output) if output.success => Ok(()),
        Ok(output) => Err(format!(
            "Docker is installed but its daemon isn't running. Start Docker Desktop (or your \
             container runtime) and try again.\n\nDetails: {}",
            output.stderr.trim()
        )),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Err(
            "Docker isn't installed on this machine. Install Docker Desktop, then try again \
             (see launcher/README.md's one-time setup section)."
                .to_string(),
        ),
        Err(err) => Err(format!("Could not check the Docker runtime: {err}")),
    }
}

/// Best-effort check for whether the stack looks already up, purely to choose which state to
/// display (`StackAlreadyRunning` vs `StartingStack`). `docker compose up -d` is idempotent —
/// it's still called unconditionally afterwards, so a wrong guess here never causes duplicate
/// containers; it can only make the splash text say "starting" for an already-running stack.
fn compose_is_running(runner: &dyn CommandRunner, cfg: &LauncherConfig) -> bool {
    let compose_file = cfg.compose_file.to_string_lossy().into_owned();
    let env_file = cfg.env_file.to_string_lossy().into_owned();
    let args = [
        "compose",
        "-f",
        &compose_file,
        "--env-file",
        &env_file,
        "ps",
        "--status",
        "running",
        "-q",
    ];
    matches!(
        runner.run("docker", &args, &cfg.project_dir),
        Ok(output) if output.success && !output.stdout.trim().is_empty()
    )
}

/// True when at least one of the images the stack runs isn't on the machine yet. Cheap enough
/// to ask on every launch (`docker image inspect` is a local lookup), and it is what keeps the
/// multi-gigabyte first pull from being reported on every subsequent start.
fn images_missing(runner: &dyn CommandRunner, cfg: &LauncherConfig) -> bool {
    cfg.images.iter().any(|image| {
        !matches!(
            runner.run("docker", &["image", "inspect", image], &cfg.project_dir),
            Ok(output) if output.success
        )
    })
}

/// Downloads the published images explicitly, rather than letting `up -d` do it implicitly, so
/// the window can say what the wait is for. On a first install this is by far the longest step.
fn compose_pull(runner: &dyn CommandRunner, cfg: &LauncherConfig) -> Result<(), String> {
    let compose_file = cfg.compose_file.to_string_lossy().into_owned();
    let env_file = cfg.env_file.to_string_lossy().into_owned();
    let args = [
        "compose",
        "-f",
        &compose_file,
        "--env-file",
        &env_file,
        "pull",
    ];
    match runner.run("docker", &args, &cfg.project_dir) {
        Ok(output) if output.success => Ok(()),
        Ok(output) => Err(format!(
            "Could not download the PCB-Inspect images. Check this machine's internet \
             connection and try again.\n\nDetails: {}",
            output.stderr.trim()
        )),
        Err(err) => Err(format!("Could not run `docker compose pull`: {err}")),
    }
}

/// Places the YOLO weight if it isn't there yet, reporting progress as it arrives.
///
/// Detection is the product; starting the stack without a weight file would leave every board
/// failing at inference time with an error the operator can do nothing about. So a failed
/// download stops startup here, where the message can still say what went wrong.
fn ensure_weights(
    downloader: &dyn Downloader,
    cfg: &LauncherConfig,
    on_state: &mut impl FnMut(LauncherState),
) -> Result<(), String> {
    let Some(weights) = &cfg.weights else {
        return Ok(());
    };
    if weights.path.is_file() {
        return Ok(());
    }

    // One event per whole percent instead of one per 256 KB chunk: ~100 messages across a
    // 114 MB download rather than several hundred, which is all a progress line can show anyway.
    let mut last_percent: Option<u64> = None;
    let mut progress = |received: u64, total: Option<u64>| {
        let percent = total.filter(|t| *t > 0).map(|t| received * 100 / t);
        if percent.is_some() && percent == last_percent {
            return;
        }
        last_percent = percent;
        on_state(LauncherState::DownloadingModel {
            received_bytes: received,
            total_bytes: total,
        });
    };
    downloader.download(&weights.url, &weights.path, &mut progress)
}

fn compose_up(runner: &dyn CommandRunner, cfg: &LauncherConfig) -> Result<(), String> {
    let compose_file = cfg.compose_file.to_string_lossy().into_owned();
    let env_file = cfg.env_file.to_string_lossy().into_owned();
    let args = [
        "compose",
        "-f",
        &compose_file,
        "--env-file",
        &env_file,
        "up",
        "-d",
    ];
    match runner.run("docker", &args, &cfg.project_dir) {
        Ok(output) if output.success => Ok(()),
        Ok(output) => Err(format!(
            "`docker compose up -d` failed:\n{}",
            output.stderr.trim()
        )),
        Err(err) => Err(format!("Could not run `docker compose up -d`: {err}")),
    }
}

/// Stops the stack without removing containers/volumes (`docker compose stop`, not `down`) —
/// the tray's "Stop Stack" action. Kept separate from full teardown so the next cold start
/// after an explicit stop is still fast (containers already exist, just need restarting).
pub fn stop_stack(runner: &dyn CommandRunner, cfg: &LauncherConfig) -> Result<(), String> {
    let compose_file = cfg.compose_file.to_string_lossy().into_owned();
    let env_file = cfg.env_file.to_string_lossy().into_owned();
    let args = [
        "compose",
        "-f",
        &compose_file,
        "--env-file",
        &env_file,
        "stop",
    ];
    match runner.run("docker", &args, &cfg.project_dir) {
        Ok(output) if output.success => Ok(()),
        Ok(output) => Err(format!(
            "`docker compose stop` failed:\n{}",
            output.stderr.trim()
        )),
        Err(err) => Err(format!("Could not run `docker compose stop`: {err}")),
    }
}

/// Runs the full cold/warm start flow, invoking `on_state` for every transition (the Tauri
/// shell forwards each one to the splash window as an event) and returning the terminal state.
pub fn start_stack(
    runner: &dyn CommandRunner,
    health: &dyn HealthClient,
    downloader: &dyn Downloader,
    cfg: &LauncherConfig,
    mut on_state: impl FnMut(LauncherState),
) -> LauncherState {
    on_state(LauncherState::CheckingRuntime);
    if let Err(detail) = docker_daemon_available(runner, cfg) {
        let state = LauncherState::RuntimeUnavailable(detail);
        on_state(state.clone());
        return state;
    }

    if let Err(detail) = ensure_weights(downloader, cfg, &mut on_state) {
        let state = LauncherState::ModelUnavailable(detail);
        on_state(state.clone());
        return state;
    }

    if images_missing(runner, cfg) {
        on_state(LauncherState::PullingImages);
        if let Err(detail) = compose_pull(runner, cfg) {
            let state = LauncherState::StartupFailed(detail);
            on_state(state.clone());
            return state;
        }
    }

    let already_running = compose_is_running(runner, cfg);
    on_state(if already_running {
        LauncherState::StackAlreadyRunning
    } else {
        LauncherState::StartingStack
    });

    if let Err(detail) = compose_up(runner, cfg) {
        let state = LauncherState::StartupFailed(detail);
        on_state(state.clone());
        return state;
    }

    let deadline = Instant::now() + cfg.health_timeout;
    let mut attempt = 0u32;
    loop {
        attempt += 1;
        let detail = match health.get_health(&cfg.health_url) {
            HealthStatus::Ok => {
                on_state(LauncherState::Ready);
                return LauncherState::Ready;
            }
            HealthStatus::Degraded(detail) | HealthStatus::Unreachable(detail) => detail,
        };
        on_state(LauncherState::WaitingForHealth {
            attempt,
            detail: Some(detail.clone()),
        });

        if Instant::now() >= deadline {
            let state = LauncherState::HealthTimedOut(format!(
                "The backend did not become healthy within {}s. Last status: {detail}",
                cfg.health_timeout.as_secs()
            ));
            on_state(state.clone());
            return state;
        }
        thread::sleep(cfg.health_poll_interval);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::config::WeightsSource;
    use crate::download::testing::FakeDownloader;
    use crate::health::testing::FakeHealthClient;
    use crate::runner::testing::FakeCommandRunner;
    use std::path::PathBuf;
    use std::time::Duration;

    /// The common case in these tests: nothing to pull and nothing to download, so the runner's
    /// scripted responses line up one-to-one with the docker calls of a plain start.
    fn test_config() -> LauncherConfig {
        LauncherConfig {
            project_dir: PathBuf::from("/fake/project"),
            compose_file: PathBuf::from("/fake/project/docker-compose.yml"),
            env_file: PathBuf::from("/fake/project/.env"),
            health_url: "http://127.0.0.1:8000/health".to_string(),
            frontend_url: "http://127.0.0.1:3000".to_string(),
            health_timeout: Duration::from_millis(20),
            health_poll_interval: Duration::from_millis(0),
            images: Vec::new(),
            weights: None,
        }
    }

    fn no_downloads() -> FakeDownloader {
        FakeDownloader::failing("no download expected in this test")
    }

    fn temp_path(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "pcb-launcher-orch-{name}-{}-{:?}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ))
    }

    #[test]
    fn cold_start_reaches_ready_when_health_succeeds_immediately() {
        let cfg = test_config();
        let runner = FakeCommandRunner::new(vec![
            FakeCommandRunner::ok(""), // docker info
            FakeCommandRunner::ok(""), // compose ps -q (empty -> not running)
            FakeCommandRunner::ok(""), // compose up -d
        ]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);
        let mut states = Vec::new();

        let result = start_stack(&runner, &health, &no_downloads(), &cfg, |s| states.push(s));

        assert_eq!(result, LauncherState::Ready);
        assert_eq!(
            states,
            vec![
                LauncherState::CheckingRuntime,
                LauncherState::StartingStack,
                LauncherState::Ready,
            ]
        );
    }

    #[test]
    fn warm_start_when_compose_ps_reports_running() {
        let cfg = test_config();
        let runner = FakeCommandRunner::new(vec![
            FakeCommandRunner::ok(""),         // docker info
            FakeCommandRunner::ok("abc123\n"), // compose ps -q -> one container id
            FakeCommandRunner::ok(""),         // compose up -d (idempotent no-op)
        ]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);
        let mut states = Vec::new();

        let result = start_stack(&runner, &health, &no_downloads(), &cfg, |s| states.push(s));

        assert_eq!(result, LauncherState::Ready);
        assert!(states.contains(&LauncherState::StackAlreadyRunning));
        assert!(!states.contains(&LauncherState::StartingStack));
        // Warm start still calls `docker compose up -d` — asserting on the runner's call log
        // is what proves this test actually guards against duplicate containers, not just the
        // state sequence looking right.
        let calls = runner.calls.borrow();
        assert!(calls
            .iter()
            .any(|(program, args)| program == "docker" && args.contains(&"up".to_string())));
    }

    #[test]
    fn missing_docker_binary_is_reported_as_runtime_unavailable() {
        let cfg = test_config();
        let runner = FakeCommandRunner::new(vec![FakeCommandRunner::not_found()]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);
        let mut states = Vec::new();

        let result = start_stack(&runner, &health, &no_downloads(), &cfg, |s| states.push(s));

        match &result {
            LauncherState::RuntimeUnavailable(detail) => {
                assert!(detail.contains("Docker isn't installed"));
            }
            other => panic!("expected RuntimeUnavailable, got {other:?}"),
        }
        assert!(result.is_terminal());
    }

    #[test]
    fn docker_daemon_not_running_is_reported_as_runtime_unavailable() {
        let cfg = test_config();
        let runner = FakeCommandRunner::new(vec![FakeCommandRunner::failure(
            "Cannot connect to the Docker daemon",
        )]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);

        let result = start_stack(&runner, &health, &no_downloads(), &cfg, |_| {});

        match result {
            LauncherState::RuntimeUnavailable(detail) => {
                assert!(detail.contains("daemon isn't running"));
            }
            other => panic!("expected RuntimeUnavailable, got {other:?}"),
        }
    }

    #[test]
    fn compose_up_failure_is_reported_and_stops_before_polling_health() {
        let cfg = test_config();
        let runner = FakeCommandRunner::new(vec![
            FakeCommandRunner::ok(""),
            FakeCommandRunner::ok(""),
            FakeCommandRunner::failure("port is already allocated"),
        ]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);

        let result = start_stack(&runner, &health, &no_downloads(), &cfg, |_| {});

        match result {
            LauncherState::StartupFailed(detail) => {
                assert!(detail.contains("port is already allocated"))
            }
            other => panic!("expected StartupFailed, got {other:?}"),
        }
    }

    #[test]
    fn health_check_retries_before_succeeding() {
        let cfg = test_config();
        let runner = FakeCommandRunner::new(vec![
            FakeCommandRunner::ok(""),
            FakeCommandRunner::ok(""),
            FakeCommandRunner::ok(""),
        ]);
        let health = FakeHealthClient::new(vec![
            HealthStatus::Unreachable("connection refused".to_string()),
            HealthStatus::Degraded("db: error".to_string()),
            HealthStatus::Ok,
        ]);
        let mut states = Vec::new();

        let result = start_stack(&runner, &health, &no_downloads(), &cfg, |s| states.push(s));

        assert_eq!(result, LauncherState::Ready);
        let waiting_count = states
            .iter()
            .filter(|s| matches!(s, LauncherState::WaitingForHealth { .. }))
            .count();
        assert_eq!(waiting_count, 2);
    }

    #[test]
    fn health_check_times_out_if_never_ok() {
        let cfg = test_config();
        let runner = FakeCommandRunner::new(vec![
            FakeCommandRunner::ok(""),
            FakeCommandRunner::ok(""),
            FakeCommandRunner::ok(""),
        ]);
        // Timeout is 20ms with a 0ms poll interval — generous enough scripted responses to
        // guarantee the deadline is hit regardless of how fast the test machine loops.
        let health = FakeHealthClient::repeating(
            HealthStatus::Unreachable("connection refused".to_string()),
            10_000,
        );

        let result = start_stack(&runner, &health, &no_downloads(), &cfg, |_| {});

        match &result {
            LauncherState::HealthTimedOut(detail) => {
                assert!(detail.contains("did not become healthy"))
            }
            other => panic!("expected HealthTimedOut, got {other:?}"),
        }
        assert!(result.is_terminal());
    }

    #[test]
    fn a_missing_image_is_pulled_before_the_stack_starts() {
        let cfg = LauncherConfig {
            images: vec!["ghcr.io/acme/pcb-inspect-backend:1.0.0".to_string()],
            ..test_config()
        };
        let runner = FakeCommandRunner::new(vec![
            FakeCommandRunner::ok(""),                   // docker info
            FakeCommandRunner::failure("No such image"), // image inspect
            FakeCommandRunner::ok("pulled"),             // compose pull
            FakeCommandRunner::ok(""),                   // compose ps -q
            FakeCommandRunner::ok(""),                   // compose up -d
        ]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);
        let mut states = Vec::new();

        let result = start_stack(&runner, &health, &no_downloads(), &cfg, |s| states.push(s));

        assert_eq!(result, LauncherState::Ready);
        assert!(states.contains(&LauncherState::PullingImages));
        let calls = runner.calls.borrow();
        assert!(calls
            .iter()
            .any(|(_, args)| args.contains(&"pull".to_string())));
    }

    #[test]
    fn images_already_on_the_machine_are_not_pulled_again() {
        let cfg = LauncherConfig {
            images: vec!["ghcr.io/acme/pcb-inspect-backend:1.0.0".to_string()],
            ..test_config()
        };
        let runner = FakeCommandRunner::new(vec![
            FakeCommandRunner::ok(""),         // docker info
            FakeCommandRunner::ok("sha256:x"), // image inspect -> present
            FakeCommandRunner::ok(""),         // compose ps -q
            FakeCommandRunner::ok(""),         // compose up -d
        ]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);
        let mut states = Vec::new();

        let result = start_stack(&runner, &health, &no_downloads(), &cfg, |s| states.push(s));

        assert_eq!(result, LauncherState::Ready);
        assert!(!states.contains(&LauncherState::PullingImages));
        let calls = runner.calls.borrow();
        assert!(!calls
            .iter()
            .any(|(_, args)| args.contains(&"pull".to_string())));
    }

    #[test]
    fn a_failed_pull_is_reported_before_anything_is_started() {
        let cfg = LauncherConfig {
            images: vec!["ghcr.io/acme/pcb-inspect-backend:1.0.0".to_string()],
            ..test_config()
        };
        let runner = FakeCommandRunner::new(vec![
            FakeCommandRunner::ok(""),
            FakeCommandRunner::failure("No such image"),
            FakeCommandRunner::failure("dial tcp: lookup ghcr.io: no such host"),
        ]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);

        let result = start_stack(&runner, &health, &no_downloads(), &cfg, |_| {});

        match &result {
            LauncherState::StartupFailed(detail) => {
                assert!(detail.contains("internet connection"), "{detail}")
            }
            other => panic!("expected StartupFailed, got {other:?}"),
        }
        let calls = runner.calls.borrow();
        assert!(!calls
            .iter()
            .any(|(_, args)| args.contains(&"up".to_string())));
    }

    #[test]
    fn a_missing_model_weight_is_downloaded_with_progress() {
        let weights = temp_path("weights").join("best.pt");
        let cfg = LauncherConfig {
            weights: Some(WeightsSource {
                path: weights.clone(),
                url: "https://example.invalid/best.pt".to_string(),
            }),
            ..test_config()
        };
        let runner = FakeCommandRunner::new(vec![
            FakeCommandRunner::ok(""),
            FakeCommandRunner::ok(""),
            FakeCommandRunner::ok(""),
        ]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);
        let downloader = FakeDownloader::serving(b"weights");
        let mut states = Vec::new();

        let result = start_stack(&runner, &health, &downloader, &cfg, |s| states.push(s));

        assert_eq!(result, LauncherState::Ready);
        assert!(states
            .iter()
            .any(|s| matches!(s, LauncherState::DownloadingModel { .. })));
        assert_eq!(std::fs::read(&weights).unwrap(), b"weights");
        let _ = std::fs::remove_dir_all(weights.parent().unwrap());
    }

    #[test]
    fn an_existing_model_weight_is_never_downloaded_again() {
        let dir = temp_path("weights-present");
        std::fs::create_dir_all(&dir).unwrap();
        let weights = dir.join("best.pt");
        std::fs::write(&weights, b"already here").unwrap();
        let cfg = LauncherConfig {
            weights: Some(WeightsSource {
                path: weights,
                url: "https://example.invalid/best.pt".to_string(),
            }),
            ..test_config()
        };
        let runner = FakeCommandRunner::new(vec![
            FakeCommandRunner::ok(""),
            FakeCommandRunner::ok(""),
            FakeCommandRunner::ok(""),
        ]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);
        // Would return an error if asked for anything.
        let downloader = no_downloads();

        let result = start_stack(&runner, &health, &downloader, &cfg, |_| {});

        assert_eq!(result, LauncherState::Ready);
        assert!(downloader.requested.borrow().is_empty());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn a_failed_weight_download_stops_startup_with_an_actionable_message() {
        let cfg = LauncherConfig {
            weights: Some(WeightsSource {
                path: temp_path("weights-fail").join("best.pt"),
                url: "https://example.invalid/best.pt".to_string(),
            }),
            ..test_config()
        };
        let runner = FakeCommandRunner::new(vec![FakeCommandRunner::ok("")]);
        let health = FakeHealthClient::new(vec![HealthStatus::Ok]);
        let downloader = FakeDownloader::failing("connection reset");

        let result = start_stack(&runner, &health, &downloader, &cfg, |_| {});

        match &result {
            LauncherState::ModelUnavailable(detail) => {
                assert!(detail.contains("connection reset"), "{detail}")
            }
            other => panic!("expected ModelUnavailable, got {other:?}"),
        }
        assert!(result.is_terminal());
        // Nothing was started: a stack whose inference worker has no weight to mount is worse
        // than one that never came up, because the failure only surfaces per board.
        let calls = runner.calls.borrow();
        assert!(!calls
            .iter()
            .any(|(_, args)| args.contains(&"up".to_string())));
    }

    #[test]
    fn stop_stack_runs_compose_stop() {
        let cfg = test_config();
        let runner = FakeCommandRunner::new(vec![FakeCommandRunner::ok("")]);

        let result = stop_stack(&runner, &cfg);

        assert!(result.is_ok());
        let calls = runner.calls.borrow();
        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0].0, "docker");
        assert!(calls[0].1.contains(&"stop".to_string()));
    }

    #[test]
    fn stop_stack_reports_failure() {
        let cfg = test_config();
        let runner = FakeCommandRunner::new(vec![FakeCommandRunner::failure("no such service")]);

        let result = stop_stack(&runner, &cfg);

        assert_eq!(
            result,
            Err("`docker compose stop` failed:\nno such service".to_string())
        );
    }
}
