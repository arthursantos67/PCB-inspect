use std::path::PathBuf;
use std::sync::Arc;

use pcb_launcher_core::{
    start_stack, stop_stack, HealthClient, LauncherConfig, LauncherState, SystemCommandRunner,
    UreqHealthClient,
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
}

impl From<&LauncherState> for StatePayload {
    fn from(state: &LauncherState) -> Self {
        match state {
            LauncherState::CheckingRuntime => Self {
                kind: "checking_runtime",
                detail: None,
                attempt: None,
            },
            LauncherState::RuntimeUnavailable(detail) => Self {
                kind: "runtime_unavailable",
                detail: Some(detail.clone()),
                attempt: None,
            },
            LauncherState::StackAlreadyRunning => Self {
                kind: "stack_already_running",
                detail: None,
                attempt: None,
            },
            LauncherState::StartingStack => Self {
                kind: "starting_stack",
                detail: None,
                attempt: None,
            },
            LauncherState::StartupFailed(detail) => Self {
                kind: "startup_failed",
                detail: Some(detail.clone()),
                attempt: None,
            },
            LauncherState::WaitingForHealth { attempt, detail } => Self {
                kind: "waiting_for_health",
                detail: detail.clone(),
                attempt: Some(*attempt),
            },
            LauncherState::Ready => Self {
                kind: "ready",
                detail: None,
                attempt: None,
            },
            LauncherState::HealthTimedOut(detail) => Self {
                kind: "health_timed_out",
                detail: Some(detail.clone()),
                attempt: None,
            },
        }
    }
}

/// The launcher expects to live next to `docker-compose.yml`/`.env` in the project's install
/// directory (PRD section 14.1's one-time setup). `PCB_LAUNCHER_PROJECT_DIR` overrides this for
/// development, so the launcher can be run from `launcher/src-tauri` against the repo root
/// during manual testing without having to relocate the binary first.
///
/// Always returned as an absolute path: `LauncherConfig` stores it (and the `docker-compose.yml`
/// / `.env` paths derived from it) for the lifetime of the app, but the `docker compose`
/// invocation itself doesn't happen until a background thread runs later (`spawn_startup`),
/// after GTK/webview/tray-icon setup — which on Linux can change the process's current working
/// directory as a side effect. A relative path resolved lazily against a since-changed CWD
/// would silently point at the wrong directory; canonicalizing here, before any of that
/// happens, makes the config immune to it.
fn resolve_project_dir() -> PathBuf {
    let dir = if let Ok(dir) = std::env::var("PCB_LAUNCHER_PROJECT_DIR") {
        PathBuf::from(dir)
    } else {
        std::env::current_exe()
            .ok()
            .and_then(|exe| exe.parent().map(|dir| dir.to_path_buf()))
            .unwrap_or_else(|| PathBuf::from("."))
    };
    std::fs::canonicalize(&dir).unwrap_or(dir)
}

/// Runs the cold/warm-start flow on a background thread so the splash window's event loop
/// never blocks, forwarding every state transition to the window and — on success — handing
/// off to the running frontend by navigating the same window there directly (no in-page JS
/// redirect needed).
fn spawn_startup(app: AppHandle, cfg: Arc<LauncherConfig>) {
    std::thread::spawn(move || {
        let runner = SystemCommandRunner;
        let health = UreqHealthClient::default();
        let app_for_events = app.clone();

        let final_state = start_stack(&runner, &health, &cfg, move |state| {
            let _ = app_for_events.emit("launcher://state", StatePayload::from(&state));
        });

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
fn get_launcher_config(cfg: tauri::State<Option<Arc<LauncherConfig>>>) -> serde_json::Value {
    match cfg.inner() {
        Some(cfg) => serde_json::json!({
            "frontend_url": cfg.frontend_url,
            "health_url": cfg.health_url,
        }),
        None => serde_json::json!({}),
    }
}

#[tauri::command]
fn retry_startup(
    app: AppHandle,
    cfg: tauri::State<Option<Arc<LauncherConfig>>>,
) -> Result<(), String> {
    match cfg.inner().clone() {
        Some(cfg) => {
            spawn_startup(app, cfg);
            Ok(())
        }
        None => Err(
            "No valid project directory configured — see launcher/README.md's one-time setup section."
                .to_string(),
        ),
    }
}

#[tauri::command]
fn stop_stack_command(cfg: tauri::State<Option<Arc<LauncherConfig>>>) -> Result<(), String> {
    match cfg.inner() {
        Some(cfg) => stop_stack(&SystemCommandRunner, cfg),
        None => Err("No valid project directory configured.".to_string()),
    }
}

fn setup_tray(app: &AppHandle, cfg: Option<Arc<LauncherConfig>>) -> tauri::Result<()> {
    let show_item = MenuItem::with_id(app, "show", "Show Dashboard", true, None::<&str>)?;
    let stop_item = MenuItem::with_id(app, "stop", "Stop Stack", true, None::<&str>)?;
    let quit_item = MenuItem::with_id(app, "quit", "Quit Launcher", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_item, &stop_item, &quit_item])?;

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
            "stop" => {
                if let Some(cfg) = &cfg {
                    if let Err(err) = stop_stack(&SystemCommandRunner, cfg) {
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

pub fn run() {
    let project_dir = resolve_project_dir();
    let cfg_result = LauncherConfig::resolve(&project_dir);
    let cfg_state: Option<Arc<LauncherConfig>> =
        cfg_result.as_ref().ok().map(|cfg| Arc::new(cfg.clone()));

    tauri::Builder::default()
        .manage(cfg_state.clone())
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

            match cfg_result {
                Ok(cfg) => spawn_startup(handle, Arc::new(cfg)),
                Err(detail) => {
                    let payload = StatePayload {
                        kind: "config_invalid",
                        detail: Some(detail),
                        attempt: None,
                    };
                    let _ = handle.emit("launcher://state", payload);
                }
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running the PCB-Inspect launcher");
}
