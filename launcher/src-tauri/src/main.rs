// Prevents an extra console window on Windows in release builds (no-op elsewhere).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    pcb_inspect_launcher_lib::run();
}
