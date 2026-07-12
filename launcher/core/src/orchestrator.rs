use std::thread;
use std::time::Instant;

use crate::config::LauncherConfig;
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
    cfg: &LauncherConfig,
    mut on_state: impl FnMut(LauncherState),
) -> LauncherState {
    on_state(LauncherState::CheckingRuntime);
    if let Err(detail) = docker_daemon_available(runner, cfg) {
        let state = LauncherState::RuntimeUnavailable(detail);
        on_state(state.clone());
        return state;
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
    use crate::health::testing::FakeHealthClient;
    use crate::runner::testing::FakeCommandRunner;
    use std::path::PathBuf;
    use std::time::Duration;

    fn test_config() -> LauncherConfig {
        LauncherConfig {
            project_dir: PathBuf::from("/fake/project"),
            compose_file: PathBuf::from("/fake/project/docker-compose.yml"),
            env_file: PathBuf::from("/fake/project/.env"),
            health_url: "http://127.0.0.1:8000/health".to_string(),
            frontend_url: "http://127.0.0.1:3000".to_string(),
            health_timeout: Duration::from_millis(20),
            health_poll_interval: Duration::from_millis(0),
        }
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

        let result = start_stack(&runner, &health, &cfg, |s| states.push(s));

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

        let result = start_stack(&runner, &health, &cfg, |s| states.push(s));

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

        let result = start_stack(&runner, &health, &cfg, |s| states.push(s));

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

        let result = start_stack(&runner, &health, &cfg, |_| {});

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

        let result = start_stack(&runner, &health, &cfg, |_| {});

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

        let result = start_stack(&runner, &health, &cfg, |s| states.push(s));

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

        let result = start_stack(&runner, &health, &cfg, |_| {});

        match &result {
            LauncherState::HealthTimedOut(detail) => {
                assert!(detail.contains("did not become healthy"))
            }
            other => panic!("expected HealthTimedOut, got {other:?}"),
        }
        assert!(result.is_terminal());
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
