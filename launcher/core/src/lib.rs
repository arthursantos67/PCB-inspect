//! Orchestration logic for the PCB-Inspect native launcher (FR-20).
//!
//! Deliberately has no GUI/Tauri dependency: `launcher/src-tauri` is a thin shell that wires
//! this crate's [`prepare_install`] and [`start_stack`] into a splash window and a tray menu.
//! Keeping the two crates separate means the logic that actually matters for the acceptance
//! criteria (first-run provisioning, cold start, warm start, error visibility) is unit-testable
//! with `cargo test` alone — no display, no Docker daemon, no system webview libraries.

mod bootstrap;
mod config;
mod download;
mod health;
mod orchestrator;
mod runner;
mod state;

pub use bootstrap::{
    image_refs, prepare_install, read_env_value, InstallLayout, InstallMode, InstallSpec,
    BUNDLED_COMPOSE, DEFAULT_REGISTRY, DEFAULT_WEIGHTS_URL,
};
pub use config::{LauncherConfig, WeightsSource};
pub use download::{Downloader, UreqDownloader};
pub use health::{HealthClient, HealthStatus, UreqHealthClient};
pub use orchestrator::{start_stack, stop_stack};
pub use runner::{CommandOutput, CommandRunner, SystemCommandRunner};
pub use state::LauncherState;
