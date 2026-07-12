/// Every state the startup flow can be in, in the order a cold start normally visits them.
/// The Tauri shell forwards each transition to the splash UI as an event; `#[derive(Clone)]`
/// lets the orchestrator both emit and return the terminal state.
#[derive(Debug, Clone, PartialEq)]
pub enum LauncherState {
    /// Checking whether the container runtime (Docker) is installed and its daemon reachable.
    CheckingRuntime,
    /// `docker info` failed or the `docker` binary isn't on PATH — the Error Visibility
    /// acceptance criterion: this must render as an actionable message, not a hang.
    RuntimeUnavailable(String),
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
            LauncherState::RuntimeUnavailable(_)
                | LauncherState::StartupFailed(_)
                | LauncherState::Ready
                | LauncherState::HealthTimedOut(_)
        )
    }

    pub fn error_detail(&self) -> Option<&str> {
        match self {
            LauncherState::RuntimeUnavailable(detail)
            | LauncherState::StartupFailed(detail)
            | LauncherState::HealthTimedOut(detail) => Some(detail),
            _ => None,
        }
    }
}
