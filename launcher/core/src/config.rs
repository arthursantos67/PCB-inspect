use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::bootstrap::{image_refs, read_env_value, InstallLayout, InstallMode, DEFAULT_REGISTRY};

/// Everything the orchestrator needs to know about *where* the PCB-Inspect stack lives and
/// *how* to tell it apart from "not started yet".
///
/// The launcher is a thin shell around the same Docker Compose stack the published images
/// describe (PRD section 14.1) — it never reimplements or rebuilds it. `project_dir` is the
/// install directory containing `docker-compose.yml` and `.env`, which the launcher provisions
/// itself on first run (see `bootstrap.rs`) rather than expecting a human to have assembled.
#[derive(Debug, Clone, PartialEq)]
pub struct LauncherConfig {
    pub project_dir: PathBuf,
    pub compose_file: PathBuf,
    pub env_file: PathBuf,
    pub health_url: String,
    pub frontend_url: String,
    pub health_timeout: Duration,
    pub health_poll_interval: Duration,
    /// Images that must be present locally before `up -d` can start anything. Empty when the
    /// stack builds from source (a checkout), where there is nothing to pull.
    pub images: Vec<String>,
    /// Where the model weight has to exist, and where to get it if it doesn't. `None` when the
    /// install is externally managed and placing the file is not the launcher's business.
    pub weights: Option<WeightsSource>,
}

/// The model weight the inference worker mounts, and the release asset it comes from.
#[derive(Debug, Clone, PartialEq)]
pub struct WeightsSource {
    pub path: PathBuf,
    pub url: String,
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
                "docker-compose.yml not found in {} — the launcher normally creates it in its \
                 own install directory on first run; see launcher/README.md.",
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
            images: Vec::new(),
            weights: None,
        })
    }

    /// Configuration for an install the launcher provisioned itself: the URLs follow the ports
    /// actually written into `.env`, the images follow the pinned version, and the weight file
    /// is the launcher's to place.
    pub fn for_install(layout: &InstallLayout, weights_url: &str) -> Result<Self, String> {
        let mut cfg = Self::resolve(&layout.project_dir)?;
        let env_file = cfg.env_file.clone();
        let value = |key: &str| read_env_value(&env_file, key);

        if let Some(port) = value("API_PORT") {
            cfg.health_url = format!("http://127.0.0.1:{port}/health");
        }
        if let Some(port) = value("FRONTEND_PORT") {
            cfg.frontend_url = format!("http://127.0.0.1:{port}");
        }
        // A checkout builds its images from source and has no registry tag to pull, which is
        // exactly the case COMPOSE_FILE marks: the build overlay is in play.
        let builds_from_source = value("COMPOSE_FILE")
            .map(|files| files.contains("docker-compose.build.yml"))
            .unwrap_or(false);
        if !builds_from_source {
            let registry = value("PCB_INSPECT_REGISTRY").unwrap_or_else(|| DEFAULT_REGISTRY.into());
            let version = value("PCB_INSPECT_VERSION").unwrap_or_else(|| "latest".into());
            cfg.images = image_refs(&registry, &version);
        }
        // Only a managed install gets its weight placed for it. In a checkout the file is the
        // developer's (root README documents the download), and `WEIGHTS_HOST_PATH` there is
        // typically relative — resolving it here would put a 114 MB download wherever the
        // process happened to start.
        if layout.mode == InstallMode::Managed {
            cfg.weights = Some(WeightsSource {
                path: layout.weights_file(),
                url: weights_url.to_string(),
            });
        }
        Ok(cfg)
    }
}
