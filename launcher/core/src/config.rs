use std::path::{Path, PathBuf};
use std::time::Duration;

/// Everything the orchestrator needs to know about *where* the PCB-Inspect stack lives and
/// *how* to tell it apart from "not started yet".
///
/// The launcher is a thin shell around the same Docker Compose stack a technical installer
/// sets up once (PRD section 14.1) — it never reimplements or rebuilds it. `project_dir` is
/// expected to be the checkout/install directory containing `docker-compose.yml` and `.env`,
/// normally resolved to the directory the launcher executable itself lives in.
#[derive(Debug, Clone, PartialEq)]
pub struct LauncherConfig {
    pub project_dir: PathBuf,
    pub compose_file: PathBuf,
    pub env_file: PathBuf,
    pub health_url: String,
    pub frontend_url: String,
    pub health_timeout: Duration,
    pub health_poll_interval: Duration,
}

impl LauncherConfig {
    /// Resolves configuration against a candidate project directory, failing fast (with an
    /// actionable message) if `docker-compose.yml` isn't there — this is what turns a missing
    /// one-time setup step into the "Error Visibility" acceptance criterion instead of a
    /// silent hang.
    pub fn resolve(project_dir: &Path) -> Result<Self, String> {
        let compose_file = project_dir.join("docker-compose.yml");
        if !compose_file.is_file() {
            return Err(format!(
                "docker-compose.yml not found in {} — see launcher/README.md's one-time setup \
                 section before double-clicking the launcher.",
                project_dir.display()
            ));
        }
        let env_file = project_dir.join(".env");
        Ok(Self {
            project_dir: project_dir.to_path_buf(),
            compose_file,
            env_file,
            health_url: "http://127.0.0.1:8000/health".to_string(),
            frontend_url: "http://127.0.0.1:3000".to_string(),
            health_timeout: Duration::from_secs(120),
            health_poll_interval: Duration::from_millis(1500),
        })
    }
}
