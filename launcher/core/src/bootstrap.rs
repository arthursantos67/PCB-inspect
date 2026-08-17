//! Turning a freshly installed application into a runnable stack, with nothing typed.
//!
//! Everything the root README used to ask a human to do by hand before the first launch —
//! place the project directory, copy `.env.example` over, invent a `SECRET_KEY` and a database
//! password, download the 114 MB model weight — happens here instead, on first run, from the
//! app's own data directory.
//!
//! Two modes, decided by where the launcher finds itself:
//!
//! - **Managed** — nothing next to the executable (a real installation: `/usr/bin` on Linux,
//!   `Program Files` on Windows). The launcher owns a directory under the user's data folder
//!   and writes `docker-compose.yml` and `.env` into it.
//! - **External** — `docker-compose.yml` already sits next to the executable, or
//!   `PCB_LAUNCHER_PROJECT_DIR` points somewhere (a checkout, or the pre-10.1 layout where the
//!   binary was copied next to the compose file). Those files belong to whoever put them there,
//!   so nothing is generated or overwritten.

use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

/// The compose file the installed system runs, compiled into the binary rather than shipped
/// beside it. A launcher and the stack description it starts are one version of one product;
/// embedding removes both the "did the resource get installed?" failure mode and any chance of
/// the two drifting apart on an operator's machine.
pub const BUNDLED_COMPOSE: &str = include_str!("../../../docker-compose.yml");

/// Where the published images come from when `.env` doesn't say otherwise.
pub const DEFAULT_REGISTRY: &str = "ghcr.io/arthursantos67";

/// The YOLO weight is a release asset rather than an image layer or a git object: 114 MB that
/// changes on its own schedule (Settings > Models swaps it at runtime, FR-12), so baking it
/// into either would mean shipping it again on every unrelated change. Pinned to its own tag
/// for the same reason. Override with `PCB_INSPECT_WEIGHTS_URL` for an offline install.
pub const DEFAULT_WEIGHTS_URL: &str =
    "https://github.com/arthursantos67/PCB-inspect/releases/download/model-v1/best.pt";

/// Keys the application owns and rewrites on every launch, so an upgraded launcher pulls the
/// images that match it instead of whatever the previous version pinned. Everything else in a
/// generated `.env` is the operator's from the moment it is first written.
const APP_OWNED_KEYS: &[&str] = &["PCB_INSPECT_REGISTRY", "PCB_INSPECT_VERSION"];

/// The database name and user the generated `.env` uses, needed both to write `DATABASE_URL`
/// and to rebuild it from an existing password.
const DEFAULT_DB_USER: &str = "pcb_inspect";
const DEFAULT_DB_NAME: &str = "pcb_inspect";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InstallMode {
    /// The launcher generates and maintains `docker-compose.yml` and `.env`.
    Managed,
    /// Someone else put them there (checkout / pre-10.1 layout); they are read, never written.
    External,
}

/// The directories an installed system reads and writes, all under one root so an uninstall has
/// exactly one place to keep (see launcher/README.md's uninstall section).
#[derive(Debug, Clone, PartialEq)]
pub struct InstallLayout {
    pub mode: InstallMode,
    pub project_dir: PathBuf,
    pub app_data_dir: PathBuf,
    pub watch_root_dir: PathBuf,
    pub weights_dir: PathBuf,
}

impl InstallLayout {
    pub fn compose_file(&self) -> PathBuf {
        self.project_dir.join("docker-compose.yml")
    }

    pub fn env_file(&self) -> PathBuf {
        self.project_dir.join(".env")
    }

    pub fn weights_file(&self) -> PathBuf {
        self.weights_dir.join("best.pt")
    }
}

/// Per-launch inputs: what the binary knows about itself.
#[derive(Debug, Clone)]
pub struct InstallSpec {
    /// `PCB_LAUNCHER_PROJECT_DIR`, when set.
    pub explicit_project_dir: Option<PathBuf>,
    /// Directory the running executable sits in.
    pub exe_dir: Option<PathBuf>,
    /// The user's data directory (`$XDG_DATA_HOME`, `%LOCALAPPDATA%`, ...).
    pub data_dir: PathBuf,
    /// Home directory, used as the default root of the browsable host filesystem on Windows.
    pub home_dir: Option<PathBuf>,
    /// Application version, pinned into `.env` as the image tag.
    pub version: String,
    pub registry: String,
    /// Contents to write as `docker-compose.yml` in managed mode.
    pub compose: &'static str,
    /// True when the host spells paths with drive letters and backslashes.
    pub windows: bool,
}

impl InstallSpec {
    /// Reads everything off the current process. `version` is the launcher's own crate version,
    /// which is also the image tag a release publishes.
    pub fn from_env(version: &str) -> Self {
        Self {
            explicit_project_dir: std::env::var_os("PCB_LAUNCHER_PROJECT_DIR").map(PathBuf::from),
            exe_dir: std::env::current_exe()
                .ok()
                .and_then(|exe| exe.parent().map(Path::to_path_buf)),
            data_dir: user_data_dir(),
            home_dir: home_dir(),
            version: std::env::var("PCB_INSPECT_VERSION").unwrap_or_else(|_| version.to_string()),
            registry: std::env::var("PCB_INSPECT_REGISTRY")
                .unwrap_or_else(|_| DEFAULT_REGISTRY.to_string()),
            compose: BUNDLED_COMPOSE,
            windows: cfg!(windows),
        }
    }
}

fn home_dir() -> Option<PathBuf> {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .filter(|p| !p.as_os_str().is_empty())
}

/// `~/.local/share/PCB-Inspect` on Linux, `%LOCALAPPDATA%\PCB-Inspect` on Windows — the
/// per-user location an installer never has to ask about and an uninstaller never touches.
fn user_data_dir() -> PathBuf {
    if cfg!(windows) {
        if let Some(local) = std::env::var_os("LOCALAPPDATA") {
            return PathBuf::from(local).join("PCB-Inspect");
        }
    }
    if let Some(xdg) = std::env::var_os("XDG_DATA_HOME").filter(|v| !v.is_empty()) {
        return PathBuf::from(xdg).join("PCB-Inspect");
    }
    match home_dir() {
        Some(home) if cfg!(target_os = "macos") => home
            .join("Library")
            .join("Application Support")
            .join("PCB-Inspect"),
        Some(home) => home.join(".local").join("share").join("PCB-Inspect"),
        None => PathBuf::from(".pcb-inspect"),
    }
}

/// Decides the install directory and whether the launcher may write to it, without touching the
/// filesystem beyond the one existence check that distinguishes the two modes.
pub fn resolve_layout(spec: &InstallSpec) -> InstallLayout {
    if let Some(dir) = &spec.explicit_project_dir {
        return external_layout(dir);
    }
    if let Some(exe_dir) = &spec.exe_dir {
        if exe_dir.join("docker-compose.yml").is_file() {
            return external_layout(exe_dir);
        }
    }
    let root = spec.data_dir.clone();
    InstallLayout {
        mode: InstallMode::Managed,
        app_data_dir: root.join("app-data"),
        watch_root_dir: root.join("watch-root"),
        weights_dir: root.join("weights"),
        project_dir: root,
    }
}

/// In external mode the paths inside `.env` are whatever that file already says; the layout's
/// data directories are only used to *generate* one, so they point at the same directory and
/// are never created.
fn external_layout(dir: &Path) -> InstallLayout {
    InstallLayout {
        mode: InstallMode::External,
        project_dir: dir.to_path_buf(),
        app_data_dir: dir.join("data").join("app-data"),
        watch_root_dir: dir.join("data").join("watch-root"),
        weights_dir: dir.join("weights"),
    }
}

/// Creates the install directory, writes the compose file, and generates `.env` if it isn't
/// there yet. Idempotent: safe on every launch, and it never overwrites an operator's settings.
pub fn prepare_install(spec: &InstallSpec) -> Result<InstallLayout, String> {
    let layout = resolve_layout(spec);
    if layout.mode == InstallMode::External {
        if !layout.compose_file().is_file() {
            return Err(format!(
                "docker-compose.yml not found in {}. Unset PCB_LAUNCHER_PROJECT_DIR to let the \
                 launcher manage its own installation instead.",
                layout.project_dir.display()
            ));
        }
        return Ok(layout);
    }

    for dir in [
        &layout.project_dir,
        &layout.app_data_dir,
        &layout.watch_root_dir,
        &layout.weights_dir,
    ] {
        fs::create_dir_all(dir)
            .map_err(|err| format!("Could not create {}: {err}", dir.display()))?;
    }

    write_if_changed(&layout.compose_file(), spec.compose)?;
    ensure_env_file(&layout.env_file(), &env_defaults(spec, &layout))?;
    Ok(layout)
}

/// Compose is rewritten only when it actually differs, so an unchanged launch leaves the file's
/// mtime alone (Docker Compose reads it either way; this just keeps a diff honest).
fn write_if_changed(path: &Path, contents: &str) -> Result<(), String> {
    if let Ok(existing) = fs::read_to_string(path) {
        if existing == contents {
            return Ok(());
        }
    }
    fs::write(path, contents).map_err(|err| format!("Could not write {}: {err}", path.display()))
}

/// The full set of variables a generated `.env` carries, in the order they are written.
fn env_defaults(spec: &InstallSpec, layout: &InstallLayout) -> Vec<(String, String)> {
    let db_password = random_hex(16);
    let secret_key = random_hex(32);
    // Docker accepts forward slashes on every platform, and `.env` interpolation treats a
    // backslash as an escape — so paths always go in POSIX-style, drive letter included.
    let path = |p: &Path| p.to_string_lossy().replace('\\', "/");

    // On Linux the operator's paths and the container's view of them differ only by the mount
    // prefix, so the whole filesystem can be exposed and mapped back. On Windows a host path has
    // no POSIX form to map back to, so the mount is rooted at the home directory and paths are
    // shown relative to it — see backend/app/core/host_paths.py.
    let (host_fs_source, host_fs_root) = if spec.windows {
        (
            spec.home_dir
                .as_deref()
                .map(path)
                .unwrap_or_else(|| "C:/Users".to_string()),
            "/".to_string(),
        )
    } else {
        ("/".to_string(), "/".to_string())
    };

    vec![
        ("PCB_INSPECT_REGISTRY".into(), spec.registry.clone()),
        ("PCB_INSPECT_VERSION".into(), spec.version.clone()),
        ("API_PORT".into(), "8000".into()),
        ("FRONTEND_PORT".into(), "3000".into()),
        ("DB_PORT".into(), "5432".into()),
        ("REDIS_PORT".into(), "6379".into()),
        ("POSTGRES_USER".into(), DEFAULT_DB_USER.into()),
        ("POSTGRES_PASSWORD".into(), db_password.clone()),
        ("POSTGRES_DB".into(), DEFAULT_DB_NAME.into()),
        ("SECRET_KEY".into(), secret_key),
        (
            "DATABASE_URL".into(),
            database_url(DEFAULT_DB_USER, &db_password, DEFAULT_DB_NAME),
        ),
        ("REDIS_URL".into(), "redis://redis:6379/0".into()),
        ("CELERY_BROKER_URL".into(), "redis://redis:6379/1".into()),
        (
            "CELERY_RESULT_BACKEND".into(),
            "redis://redis:6379/1".into(),
        ),
        ("WATCH_ROOT".into(), "/data/watch-root".into()),
        ("APP_DATA_DIR".into(), "/data/app-data".into()),
        ("WATCH_ROOT_HOST_PATH".into(), path(&layout.watch_root_dir)),
        ("APP_DATA_HOST_PATH".into(), path(&layout.app_data_dir)),
        ("WEIGHTS_HOST_PATH".into(), path(&layout.weights_dir)),
        ("HOST_FS_SOURCE".into(), host_fs_source),
        ("HOST_FS_ROOT".into(), host_fs_root),
        ("HOST_FS_MOUNT".into(), "/hostfs".into()),
        ("LLM_PROVIDER".into(), "openai_compatible".into()),
        (
            "LLM_BASE_URL".into(),
            "http://host.docker.internal:1234/v1".into(),
        ),
        ("LLM_MODEL".into(), "local-model".into()),
        ("LLM_API_KEY".into(), String::new()),
        ("LLM_TIMEOUT_S".into(), "600".into()),
        ("NEXT_PUBLIC_API_URL".into(), "http://localhost:8000".into()),
        (
            "CORS_ALLOW_ORIGINS".into(),
            "http://localhost:3000,http://127.0.0.1:3000".into(),
        ),
    ]
}

fn database_url(user: &str, password: &str, db: &str) -> String {
    format!("postgresql+asyncpg://{user}:{password}@db:5432/{db}")
}

/// The password inside a `postgresql+asyncpg://user:password@host:port/db` URL.
///
/// Split at the *last* `@` so a password containing one is still read whole; the generated
/// password never does, but an operator's hand-written URL may.
fn password_from_database_url(url: &str) -> Option<String> {
    let (_, credentials) = url.split_once("//")?;
    let (credentials, _) = credentials.rsplit_once('@')?;
    let (_, password) = credentials.split_once(':')?;
    (!password.is_empty()).then(|| password.to_string())
}

/// Keeps the database password and the URL that embeds it as one value, not two.
///
/// [`env_defaults`] invents a fresh password on every call, and [`ensure_env_file`] fills in
/// missing keys one at a time — so an `.env` carrying only one half of the pair (hand-edited,
/// or written by a launcher version that predates the other key) would get the other half
/// filled with a *different* random password. Postgres would then come up with one password
/// while the API connects with another, and the resulting authentication error names neither
/// key. Whatever the operator's file already says wins, and the missing half is derived from it.
fn reconcile_database_password(existing: &str, defaults: &mut [(String, String)]) {
    let value_of = |wanted: &str| {
        existing.lines().find_map(|line| {
            let (key, value) = line.trim().split_once('=')?;
            (key.trim() == wanted).then(|| value.trim().to_string())
        })
    };
    let Some(password) = value_of("POSTGRES_PASSWORD").filter(|p| !p.is_empty()).or_else(|| {
        value_of("DATABASE_URL").as_deref().and_then(password_from_database_url)
    }) else {
        // Neither half is there: the file predates both, and the fresh defaults already agree.
        return;
    };
    let user = value_of("POSTGRES_USER").unwrap_or_else(|| DEFAULT_DB_USER.to_string());
    let db = value_of("POSTGRES_DB").unwrap_or_else(|| DEFAULT_DB_NAME.to_string());

    for (key, value) in defaults.iter_mut() {
        match key.as_str() {
            "POSTGRES_PASSWORD" => *value = password.clone(),
            "DATABASE_URL" => *value = database_url(&user, &password, &db),
            _ => {}
        }
    }
}

/// Writes `.env` on first run and, afterwards, only fills in what a newer version added.
///
/// The operator's file is authoritative: a key already present keeps its value, so a changed
/// port or LLM endpoint survives every upgrade. The exceptions are [`APP_OWNED_KEYS`], which
/// the launcher rewrites because they describe the launcher itself.
fn ensure_env_file(path: &Path, defaults: &[(String, String)]) -> Result<(), String> {
    let existing = fs::read_to_string(path).ok();
    let Some(existing) = existing else {
        let header = "# Generated by the PCB-Inspect launcher on first run. Safe to edit: only\n\
                      # PCB_INSPECT_REGISTRY and PCB_INSPECT_VERSION are rewritten on upgrade.\n\
                      # Never expose these ports beyond 127.0.0.1 (PRD section 13).\n\n";
        let body: String = defaults
            .iter()
            .map(|(key, value)| format!("{key}={value}\n"))
            .collect();
        return write_env(path, &format!("{header}{body}"));
    };

    let mut defaults = defaults.to_vec();
    reconcile_database_password(&existing, &mut defaults);

    let present: HashSet<&str> = existing.lines().filter_map(env_key).collect();
    let mut updated: Vec<String> = existing
        .lines()
        .map(|line| match env_key(line) {
            Some(key) if APP_OWNED_KEYS.contains(&key) => defaults
                .iter()
                .find(|(k, _)| k == key)
                .map(|(k, v)| format!("{k}={v}"))
                .unwrap_or_else(|| line.to_string()),
            _ => line.to_string(),
        })
        .collect();

    let added: Vec<&(String, String)> = defaults
        .iter()
        .filter(|(key, _)| !present.contains(key.as_str()))
        .collect();
    if !added.is_empty() {
        updated.push(String::new());
        updated.push("# Added by a newer version of the launcher.".to_string());
        updated.extend(added.iter().map(|(k, v)| format!("{k}={v}")));
    }

    write_env(path, &format!("{}\n", updated.join("\n")))
}

/// Holds the database password and the session-signing key, so on Unix it is written
/// owner-only rather than inheriting the process umask.
fn write_env(path: &Path, contents: &str) -> Result<(), String> {
    fs::write(path, contents)
        .map_err(|err| format!("Could not write {}: {err}", path.display()))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

fn env_key(line: &str) -> Option<&str> {
    let line = line.trim();
    if line.is_empty() || line.starts_with('#') {
        return None;
    }
    line.split_once('=').map(|(key, _)| key.trim())
}

/// Hex-encoded random bytes for the generated secrets. `.env.example` shipping
/// `SECRET_KEY=change-me-to-a-random-value` is exactly the install-time step that never got
/// done, so nothing here has a placeholder to leave behind.
fn random_hex(bytes: usize) -> String {
    let mut buf = vec![0u8; bytes];
    getrandom::getrandom(&mut buf).expect("operating system random number generator unavailable");
    buf.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// The images `docker compose` will need, so the launcher can tell "not downloaded yet" from
/// "already here" before deciding whether to show a multi-gigabyte pull as a step of its own.
pub fn image_refs(registry: &str, version: &str) -> Vec<String> {
    ["backend", "frontend"]
        .iter()
        .map(|name| format!("{registry}/pcb-inspect-{name}:{version}"))
        .collect()
}

/// Reads a key out of an existing `.env`, used to honour an operator's edits (registry, version,
/// paths) rather than assuming the generated defaults are still in force.
pub fn read_env_value(env_file: &Path, key: &str) -> Option<String> {
    let contents = fs::read_to_string(env_file).ok()?;
    contents.lines().find_map(|line| {
        let (k, v) = line.trim().split_once('=')?;
        (k.trim() == key).then(|| v.trim().to_string())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_dir(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "pcb-launcher-{name}-{}-{}",
            std::process::id(),
            random_hex(4)
        ));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn spec_for(root: &Path) -> InstallSpec {
        InstallSpec {
            explicit_project_dir: None,
            exe_dir: Some(root.join("bin")),
            data_dir: root.join("data"),
            home_dir: Some(root.join("home")),
            version: "1.2.3".to_string(),
            registry: DEFAULT_REGISTRY.to_string(),
            compose: "services: {}\n",
            windows: false,
        }
    }

    #[test]
    fn first_run_creates_directories_compose_and_env() {
        let root = temp_dir("first-run");
        let layout = prepare_install(&spec_for(&root)).unwrap();

        assert_eq!(layout.mode, InstallMode::Managed);
        assert!(layout.app_data_dir.is_dir());
        assert!(layout.watch_root_dir.is_dir());
        assert!(layout.weights_dir.is_dir());
        assert_eq!(
            fs::read_to_string(layout.compose_file()).unwrap(),
            "services: {}\n"
        );
        let env = fs::read_to_string(layout.env_file()).unwrap();
        assert!(env.contains("PCB_INSPECT_VERSION=1.2.3"));
        assert!(env.contains(&format!(
            "WEIGHTS_HOST_PATH={}",
            layout.weights_dir.display()
        )));
    }

    #[test]
    fn generated_secrets_are_random_and_not_placeholders() {
        let one = prepare_install(&spec_for(&temp_dir("secret-a"))).unwrap();
        let two = prepare_install(&spec_for(&temp_dir("secret-b"))).unwrap();

        let secret =
            |layout: &InstallLayout| read_env_value(&layout.env_file(), "SECRET_KEY").unwrap();
        let password = |layout: &InstallLayout| {
            read_env_value(&layout.env_file(), "POSTGRES_PASSWORD").unwrap()
        };

        assert_eq!(secret(&one).len(), 64);
        assert_ne!(secret(&one), secret(&two));
        assert_ne!(password(&one), password(&two));
        assert!(!secret(&one).contains("change-me"));
        // The database URL has to carry the same generated password, or the api container
        // authenticates against a database it just created with a different one.
        let url = read_env_value(&one.env_file(), "DATABASE_URL").unwrap();
        assert!(url.contains(&password(&one)), "{url}");
    }

    #[test]
    fn second_run_keeps_operator_edits_but_refreshes_the_pinned_version() {
        let root = temp_dir("upgrade");
        let spec = spec_for(&root);
        let layout = prepare_install(&spec).unwrap();
        let original_secret = read_env_value(&layout.env_file(), "SECRET_KEY").unwrap();

        let edited = fs::read_to_string(layout.env_file())
            .unwrap()
            .replace("API_PORT=8000", "API_PORT=8123");
        fs::write(layout.env_file(), edited).unwrap();

        let upgraded = InstallSpec {
            version: "2.0.0".to_string(),
            ..spec
        };
        prepare_install(&upgraded).unwrap();

        assert_eq!(
            read_env_value(&layout.env_file(), "API_PORT").as_deref(),
            Some("8123")
        );
        assert_eq!(
            read_env_value(&layout.env_file(), "SECRET_KEY").as_deref(),
            Some(original_secret.as_str())
        );
        assert_eq!(
            read_env_value(&layout.env_file(), "PCB_INSPECT_VERSION").as_deref(),
            Some("2.0.0")
        );
    }

    #[test]
    fn a_key_added_by_a_newer_version_is_appended_without_touching_the_rest() {
        let root = temp_dir("new-key");
        let layout = resolve_layout(&spec_for(&root));
        fs::create_dir_all(&layout.project_dir).unwrap();
        fs::write(layout.env_file(), "API_PORT=9000\n").unwrap();

        prepare_install(&spec_for(&root)).unwrap();

        let env = fs::read_to_string(layout.env_file()).unwrap();
        assert!(env.starts_with("API_PORT=9000"));
        assert!(env.contains("SECRET_KEY="));
        assert!(env.contains("Added by a newer version"));
    }

    #[test]
    fn a_half_written_database_pair_is_completed_from_what_the_file_already_has() {
        // An `.env` that kept its password but lost `DATABASE_URL` (hand-edited, or written by
        // an older launcher): filling the URL in with a freshly generated password would point
        // the API at a database it can no longer authenticate against.
        let root = temp_dir("derived-url");
        let layout = resolve_layout(&spec_for(&root));
        fs::create_dir_all(&layout.project_dir).unwrap();
        fs::write(
            layout.env_file(),
            "POSTGRES_USER=pcb_inspect\nPOSTGRES_PASSWORD=hunter2\nPOSTGRES_DB=pcb_inspect\n",
        )
        .unwrap();

        prepare_install(&spec_for(&root)).unwrap();

        assert_eq!(
            read_env_value(&layout.env_file(), "POSTGRES_PASSWORD").as_deref(),
            Some("hunter2")
        );
        assert_eq!(
            read_env_value(&layout.env_file(), "DATABASE_URL").as_deref(),
            Some("postgresql+asyncpg://pcb_inspect:hunter2@db:5432/pcb_inspect")
        );
    }

    #[test]
    fn a_missing_password_is_recovered_from_the_database_url() {
        let root = temp_dir("derived-password");
        let layout = resolve_layout(&spec_for(&root));
        fs::create_dir_all(&layout.project_dir).unwrap();
        fs::write(
            layout.env_file(),
            "DATABASE_URL=postgresql+asyncpg://pcb_inspect:s3cret@db:5432/pcb_inspect\n",
        )
        .unwrap();

        prepare_install(&spec_for(&root)).unwrap();

        assert_eq!(
            read_env_value(&layout.env_file(), "POSTGRES_PASSWORD").as_deref(),
            Some("s3cret")
        );
        assert_eq!(
            read_env_value(&layout.env_file(), "DATABASE_URL").as_deref(),
            Some("postgresql+asyncpg://pcb_inspect:s3cret@db:5432/pcb_inspect")
        );
    }

    #[test]
    fn a_checkout_next_to_the_executable_is_never_written_to() {
        let root = temp_dir("external");
        let project = root.join("checkout");
        fs::create_dir_all(&project).unwrap();
        fs::write(project.join("docker-compose.yml"), "# mine\n").unwrap();
        let spec = InstallSpec {
            exe_dir: Some(project.clone()),
            ..spec_for(&root)
        };

        let layout = prepare_install(&spec).unwrap();

        assert_eq!(layout.mode, InstallMode::External);
        assert_eq!(layout.project_dir, project);
        assert_eq!(
            fs::read_to_string(project.join("docker-compose.yml")).unwrap(),
            "# mine\n"
        );
        assert!(!project.join(".env").exists());
    }

    #[test]
    fn explicit_project_dir_without_a_compose_file_is_an_actionable_error() {
        let root = temp_dir("explicit-missing");
        let spec = InstallSpec {
            explicit_project_dir: Some(root.join("nowhere")),
            ..spec_for(&root)
        };

        let err = prepare_install(&spec).unwrap_err();

        assert!(err.contains("docker-compose.yml not found"), "{err}");
    }

    #[test]
    fn windows_roots_the_host_filesystem_mount_at_the_home_directory() {
        let root = temp_dir("windows");
        let spec = InstallSpec {
            windows: true,
            home_dir: Some(PathBuf::from("C:\\Users\\op")),
            ..spec_for(&root)
        };

        let layout = prepare_install(&spec).unwrap();
        let env_file = layout.env_file();

        assert_eq!(
            read_env_value(&env_file, "HOST_FS_SOURCE").as_deref(),
            Some("C:/Users/op")
        );
        assert_eq!(
            read_env_value(&env_file, "HOST_FS_ROOT").as_deref(),
            Some("/")
        );
    }

    #[test]
    fn image_refs_follow_the_registry_and_version() {
        assert_eq!(
            image_refs("ghcr.io/acme", "1.4.0"),
            vec![
                "ghcr.io/acme/pcb-inspect-backend:1.4.0".to_string(),
                "ghcr.io/acme/pcb-inspect-frontend:1.4.0".to_string(),
            ]
        );
    }

    #[test]
    fn the_bundled_compose_file_is_the_one_this_repo_ships() {
        assert!(BUNDLED_COMPOSE.contains("pcb-inspect-backend"));
        // If it carried build sections it would be unusable on a machine with no source tree,
        // which is the whole reason docker-compose.build.yml exists. Checked per line so the
        // header comment explaining that is not mistaken for one.
        let build_section = BUNDLED_COMPOSE
            .lines()
            .find(|line| line.trim_start().starts_with("build:"));
        assert_eq!(build_section, None);
    }
}
