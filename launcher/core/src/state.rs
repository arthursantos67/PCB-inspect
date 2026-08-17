/// Every state the startup flow can be in, in the order a cold start normally visits them.
/// The Tauri shell forwards each transition to the splash UI as an event; `#[derive(Clone)]`
/// lets the orchestrator both emit and return the terminal state.
#[derive(Debug, Clone, PartialEq)]
pub enum LauncherState {
    /// Creating the install directory, writing `docker-compose.yml` and generating `.env` on
    /// first run (see `bootstrap.rs`). Normally too fast to read.
    PreparingInstall,
    /// The install directory could not be provisioned (unwritable data directory, or an
    /// explicitly configured project directory with no compose file in it). Terminal.
    InstallFailed(String),
    /// Checking whether the container runtime (Docker) is installed and its daemon reachable.
    CheckingRuntime,
    /// `docker info` failed or the `docker` binary isn't on PATH — the Error Visibility
    /// acceptance criterion: this must render as an actionable message, not a hang.
    RuntimeUnavailable(String),
    /// Downloading the YOLO weight, which only happens once and is the longest single step of a
    /// first launch — reported with byte counts so the window can show real progress rather
    /// than an unmoving spinner. `total_bytes` is absent when the server declares no length.
    DownloadingModel {
        received_bytes: u64,
        total_bytes: Option<u64>,
    },
    /// The weight could not be placed, so inference would fail on every board. Terminal.
    ModelUnavailable(String),
    /// Pulling the published images, the multi-gigabyte step of a first launch. Skipped
    /// entirely once they are on the machine, and when the stack builds from source.
    PullingImages,
    /// The stack was already up when the launcher checked — the Warm Start path. `docker
    /// compose up -d` still runs (see orchestrator docs) but is a no-op against already-running
    /// containers, so no duplicates are created.
    StackAlreadyRunning,
    /// The stack was down; `docker compose up -d` is starting it now — the Cold Start path.
    StartingStack,
    /// `docker compose up -d` returned a non-zero exit code.
    StartupFailed(String),
    /// Containers are up; polling `/health` until it reports `"status": "ok"`.
    WaitingForHealth {
        attempt: u32,
        detail: Option<String>,
    },
    /// `/health` reported `"status": "ok"`. Terminal success state.
    Ready,
    /// `/health` never reported `"status": "ok"` within the configured timeout.
    HealthTimedOut(String),
}

impl LauncherState {
    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            LauncherState::InstallFailed(_)
                | LauncherState::RuntimeUnavailable(_)
                | LauncherState::ModelUnavailable(_)
                | LauncherState::StartupFailed(_)
                | LauncherState::Ready
                | LauncherState::HealthTimedOut(_)
        )
    }

    pub fn error_detail(&self) -> Option<&str> {
        match self {
            LauncherState::InstallFailed(detail)
            | LauncherState::RuntimeUnavailable(detail)
            | LauncherState::ModelUnavailable(detail)
            | LauncherState::StartupFailed(detail)
            | LauncherState::HealthTimedOut(detail) => Some(detail),
            _ => None,
        }
    }
}
