//! Orchestration logic for the PCB-Inspect native launcher (FR-20).
//!
//! Deliberately has no GUI/Tauri dependency: `launcher/src-tauri` is a thin shell that wires
//! this crate's [`start_stack`] into a splash window and a tray menu. Keeping the two crates
//! separate means the logic that actually matters for the acceptance criteria (cold start,
//! warm start, error visibility) is unit-testable with `cargo test` alone — no display, no
//! Docker daemon, no system webview libraries required.

mod config;
mod health;
mod orchestrator;
mod runner;
mod state;

pub use config::LauncherConfig;
pub use health::{HealthClient, HealthStatus, UreqHealthClient};
pub use orchestrator::{start_stack, stop_stack};
pub use runner::{CommandOutput, CommandRunner, SystemCommandRunner};
pub use state::LauncherState;
