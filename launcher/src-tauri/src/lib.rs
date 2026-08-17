use std::sync::{Arc, Mutex};

use pcb_launcher_core::{
    prepare_install, start_stack, stop_stack, InstallSpec, LauncherConfig, LauncherState,
    SystemCommandRunner, UreqDownloader, UreqHealthClient, DEFAULT_WEIGHTS_URL,
};
use serde::Serialize;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager, WindowEvent};

/// JSON-friendly mirror of `pcb_launcher_core::LauncherState`, sent to the splash window as
/// the `launcher://state` event. `LauncherState` itself intentionally stays free of any
/// serde/GUI dependency (see launcher/core/src/lib.rs), so the mapping happens here instead.
#[derive(Serialize, Clone)]
struct StatePayload {
    kind: &'static str,
    detail: Option<String>,
    attempt: Option<u32>,
    /// Only ever set while the model weight downloads, so the splash can show a real bar
    /// instead of a spinner during the longest step of a first launch.
    progress: Option<f64>,
}

impl StatePayload {
    fn of(kind: &'static str) -> Self {
        Self {
            kind,
            detail: None,
            attempt: None,
            progress: None,
        }
    }

    fn with_detail(kind: &'static str, detail: &str) -> Self {
        Self {
            detail: Some(detail.to_string()),
            ..Self::of(kind)
        }
    }
}

impl From<&LauncherState> for StatePayload {
    fn from(state: &LauncherState) -> Self {
        match state {
            LauncherState::PreparingInstall => Self::of("preparing_install"),
            LauncherState::InstallFailed(detail) => Self::with_detail("install_failed", detail),
            LauncherState::DownloadingModel {
                received_bytes,
                total_bytes,
            } => Self {
                progress: total_bytes
                    .filter(|total| *total > 0)
                    .map(|total| *received_bytes as f64 / total as f64),
                detail: Some(format!(
                    "{} of {}",
                    format_bytes(*received_bytes),
                    total_bytes.map(format_bytes).unwrap_or_else(|| "?".into())
                )),
                ..Self::of("downloading_model")
            },
            LauncherState::ModelUnavailable(detail) => {
                Self::with_detail("model_unavailable", detail)
            }
            LauncherState::PullingImages => Self::of("pulling_images"),
            LauncherState::CheckingRuntime => Self::of("checking_runtime"),
            LauncherState::RuntimeUnavailable(detail) => {
                Self::with_detail("runtime_unavailable", detail)
            }
            LauncherState::StackAlreadyRunning => Self::of("stack_already_running"),
            LauncherState::StartingStack => Self::of("starting_stack"),
            LauncherState::StartupFailed(detail) => Self::with_detail("startup_failed", detail),
            LauncherState::WaitingForHealth { attempt, detail } => Self {
                detail: detail.clone(),
                attempt: Some(*attempt),
                ..Self::of("waiting_for_health")
            },
            LauncherState::Ready => Self::of("ready"),
            LauncherState::HealthTimedOut(detail) => Self::with_detail("health_timed_out", detail),
        }
    }
}

/// Download progress is for a person watching a window, so it is rounded to something readable
/// rather than exact.
fn format_bytes(bytes: u64) -> String {
    const MB: f64 = 1024.0 * 1024.0;
    format!("{:.0} MB", bytes as f64 / MB)
}

/// The configuration only exists once the install has been provisioned, which happens on a
/// background thread (see `spawn_startup`) — but the tray menu and the `stop_stack`/`reload`
/// commands are reachable before then. Sharing it behind a lock lets those paths report
/// "not ready yet" instead of the app having to block its own startup on disk work.
type SharedConfig = Arc<Mutex<Option<Arc<LauncherConfig>>>>;

fn current_config(shared: &SharedConfig) -> Option<Arc<LauncherConfig>> {
    // A panic in one of the short critical sections below must not turn every later tray click
    // into a panic of its own; the data behind the lock is a plain `Option<Arc<…>>` that cannot
    // be left half-written.
    shared
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .clone()
}

/// The release asset the model weight is fetched from. Overridable so an air-gapped or
/// mirrored install can point the first run at its own copy without a rebuild.
fn weights_url() -> String {
    std::env::var("PCB_INSPECT_WEIGHTS_URL").unwrap_or_else(|_| DEFAULT_WEIGHTS_URL.to_string())
}

/// Runs first-run provisioning and then the cold/warm-start flow on a background thread so the
/// splash window's event loop never blocks, forwarding every state transition to the window
/// and — on success — handing off to the running frontend by navigating the same window there
/// directly (no in-page JS redirect needed).
///
/// Provisioning belongs on this thread rather than in `run()` so that a failure is something
/// the user sees in the splash *and* can retry, instead of a dead window that only a restart
/// clears.
fn spawn_startup(app: AppHandle, shared: SharedConfig) {
    std::thread::spawn(move || {
        let app_for_events = app.clone();
        let emit = move |state: &LauncherState| {
            let _ = app_for_events.emit("launcher://state", StatePayload::from(state));
        };

        emit(&LauncherState::PreparingInstall);
        let prepared = prepare_install(&InstallSpec::from_env(env!("CARGO_PKG_VERSION")))
            .and_then(|layout| LauncherConfig::for_install(&layout, &weights_url()));
        let cfg = match prepared {
            Ok(cfg) => Arc::new(cfg),
            Err(detail) => {
                emit(&LauncherState::InstallFailed(detail));
                return;
            }
        };
        *shared
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner()) = Some(cfg.clone());

        let runner = SystemCommandRunner;
        let health = UreqHealthClient::default();
        let downloader = UreqDownloader::default();

        let final_state = start_stack(&runner, &health, &downloader, &cfg, |state| emit(&state));

        if final_state == LauncherState::Ready {
            if let Some(window) = app.get_webview_window("main") {
                match cfg.frontend_url.parse() {
                    Ok(url) => {
                        let _ = window.navigate(url);
                    }
                    Err(err) => {
                        eprintln!("invalid frontend_url {:?}: {err}", cfg.frontend_url);
                    }
                }
            }
        }
    });
}

#[tauri::command]
fn get_launcher_config(cfg: tauri::State<SharedConfig>) -> serde_json::Value {
    match current_config(cfg.inner()) {
        Some(cfg) => serde_json::json!({
            "frontend_url": cfg.frontend_url,
            "health_url": cfg.health_url,
        }),
        None => serde_json::json!({}),
    }
}

/// Retries the whole flow, provisioning included — the failure being retried may well be the
/// provisioning step itself (no disk space, a directory the user has since fixed permissions on).
#[tauri::command]
fn retry_startup(app: AppHandle, cfg: tauri::State<SharedConfig>) -> Result<(), String> {
    spawn_startup(app, cfg.inner().clone());
    Ok(())
}

#[tauri::command]
fn stop_stack_command(cfg: tauri::State<SharedConfig>) -> Result<(), String> {
    match current_config(cfg.inner()) {
        Some(cfg) => stop_stack(&SystemCommandRunner, &cfg),
        None => Err("The stack has not been started yet.".to_string()),
    }
}

fn setup_tray(app: &AppHandle, cfg: SharedConfig) -> tauri::Result<()> {
    let show_item = MenuItem::with_id(app, "show", "Show Dashboard", true, None::<&str>)?;
    let reload_item = MenuItem::with_id(app, "reload", "Reload Dashboard", true, None::<&str>)?;
    let stop_item = MenuItem::with_id(app, "stop", "Stop Stack", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit Launcher", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &reload_item, &stop_item, &quit_item])?;

    let mut builder = TrayIconBuilder::new()
        .menu(&menu)
        .tooltip("PCB-Inspect Launcher");
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }

    builder
        .on_menu_event(move |app_handle, event| match event.id.as_ref() {
            "show" => {
                if let Some(window) = app_handle.get_webview_window("main") {
                    let _ = window.show();
                    let _ = window.set_focus();
                }
            }
            // The window keeps whatever page it loaded at startup, and WebKitGTK gives the
            // user no reload shortcut of their own — so after the containers are rebuilt the
            // dashboard can sit there showing the previous version with no way back short of
            // restarting the launcher. Re-navigating to the frontend URL loads it fresh.
            "reload" => {
                if let (Some(window), Some(cfg)) =
                    (app_handle.get_webview_window("main"), current_config(&cfg))
                {
                    match cfg.frontend_url.parse() {
                        Ok(url) => {
                            let _ = window.navigate(url);
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                        Err(err) => eprintln!("invalid frontend_url {:?}: {err}", cfg.frontend_url),
                    }
                }
            }
            "stop" => {
                if let Some(cfg) = current_config(&cfg) {
                    if let Err(err) = stop_stack(&SystemCommandRunner, &cfg) {
                        eprintln!("stop stack failed: {err}");
                    }
                }
            }
            "quit" => app_handle.exit(0),
            _ => {}
        })
        .build(app)?;
    Ok(())
}

/// WebKitGTK gives the window no reload of its own (no address bar, no context-menu entry,
/// no default F5 binding), and the tray menu's "Reload Dashboard" is out of reach on desktops
/// that hide tray icons — GNOME without an AppIndicator extension, which is what this app is
/// developed on. Without this, a dashboard loaded before a `docker compose up -d --build`
/// keeps showing the previous version until the whole launcher is restarted. Injected on every
/// page load, so it survives navigation inside the frontend.
const RELOAD_SHORTCUT_SCRIPT: &str = r#"
(function () {
  if (window.__pcbInspectReloadBound) return;
  window.__pcbInspectReloadBound = true;
  window.addEventListener("keydown", function (event) {
    const reload =
      event.key === "F5" || ((event.ctrlKey || event.metaKey) && (event.key === "r" || event.key === "R"));
    if (reload) {
      event.preventDefault();
      window.location.reload();
    }
  });
})();
"#;

pub fn run() {
    let cfg_state: SharedConfig = Arc::new(Mutex::new(None));

    tauri::Builder::default()
        .manage(cfg_state.clone())
        .on_page_load(|webview, _payload| {
            let _ = webview.eval(RELOAD_SHORTCUT_SCRIPT);
        })
        .invoke_handler(tauri::generate_handler![
            get_launcher_config,
            retry_startup,
            stop_stack_command
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            setup_tray(&handle, cfg_state.clone())?;

            // Closing the window hides it instead of quitting — the backend stack (and the
            // launcher's tray icon) keep running so re-opening is instant. Documented in
            // launcher/README.md's Lifecycle section; use the tray's "Quit Launcher" to exit
            // the app process, and "Stop Stack" to actually stop the containers.
            if let Some(window) = handle.get_webview_window("main") {
                let window_for_close = window.clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        let _ = window_for_close.hide();
                    }
                });
            }

            spawn_startup(handle, cfg_state.clone());

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the PCB-Inspect launcher");
}
