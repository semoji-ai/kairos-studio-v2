// Prevents an extra console window on Windows in release; harmless in dev.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    kairos_studio_lib::run();
}
