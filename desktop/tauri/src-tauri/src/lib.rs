use std::{
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager, Url,
};

const UI_URL: &str = "http://127.0.0.1:8051/les";
const HEALTH_URL: &str = "http://127.0.0.1:8051/healthz";

fn endpoint_ready(url: &str) -> bool {
    let Ok(parsed) = url.parse::<Url>() else {
        return false;
    };
    let Some(host) = parsed.host_str() else {
        return false;
    };
    let Some(port) = parsed.port_or_known_default() else {
        return false;
    };
    let Ok(addr) = format!("{host}:{port}").parse::<SocketAddr>() else {
        return false;
    };
    let Ok(mut stream) = TcpStream::connect_timeout(&addr, Duration::from_millis(450)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(800)));
    let path = if parsed.path().is_empty() { "/" } else { parsed.path() };
    let request = format!(
        "GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n"
    );
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = String::new();
    if stream.read_to_string(&mut response).is_err() {
        return false;
    }
    let status_ok = response.lines().next().is_some_and(|line| line.contains(" 200 "));
    status_ok && response.contains("\"service\":\"sovushka\"")
}

fn runtime_urls(_app: &AppHandle) -> (String, String) {
    #[cfg(target_os = "windows")]
    {
        let persistent_state = std::env::var_os("LES_WINDOWS_STATE_ROOT")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("LOCALAPPDATA").map(|path| PathBuf::from(path).join("LES")))
            .map(|root| root.join("logs/windows-light-state.json"));
        let legacy_state = resource_dir(_app)
            .ok()
            .map(|resources| resources.join("runtime/logs/windows-light-state.json"));
        for state in persistent_state.into_iter().chain(legacy_state) {
            if let Ok(text) = std::fs::read_to_string(state) {
                if let Ok(payload) = serde_json::from_str::<serde_json::Value>(&text) {
                    let ui = payload.get("ui_url").and_then(|value| value.as_str());
                    let health = payload.get("ui_health_url").and_then(|value| value.as_str());
                    if let (Some(ui), Some(health)) = (ui, health) {
                        return (ui.to_string(), health.to_string());
                    }
                }
            }
        }
    }
    (UI_URL.to_string(), HEALTH_URL.to_string())
}

fn ui_ready(app: &AppHandle) -> bool {
    let (_, health) = runtime_urls(app);
    endpoint_ready(&health)
}

fn resource_dir(app: &AppHandle) -> Result<PathBuf, String> {
    app.path().resource_dir().map_err(|error| error.to_string())
}

#[cfg(target_os = "windows")]
fn bootstrap_status_path() -> Option<PathBuf> {
    std::env::var_os("LES_WINDOWS_STATE_ROOT")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("LOCALAPPDATA").map(|path| PathBuf::from(path).join("LES")))
        .map(|root| root.join("logs/bootstrap-status.json"))
}

fn bootstrap_failure_message(status: &std::process::ExitStatus) -> String {
    #[cfg(target_os = "windows")]
    if let Some(path) = bootstrap_status_path() {
        if let Ok(text) = std::fs::read_to_string(&path) {
            if let Ok(payload) = serde_json::from_str::<serde_json::Value>(&text) {
                let message = payload.get("message").and_then(|value| value.as_str()).unwrap_or("");
                let code = payload.get("code").and_then(|value| value.as_str()).unwrap_or("");
                let install_url = payload
                    .get("install_url")
                    .and_then(|value| value.as_str())
                    .unwrap_or("");
                let log_path = payload.get("log_path").and_then(|value| value.as_str()).unwrap_or("");
                if !message.is_empty() {
                    let mut lines = vec![message.to_string()];
                    if !code.is_empty() {
                        lines.push(format!("Код: {code}"));
                    }
                    if !install_url.is_empty() {
                        lines.push(format!("Установка: {install_url}"));
                    }
                    if !log_path.is_empty() {
                        lines.push(format!("Журнал: {log_path}"));
                    }
                    return lines.join("\n");
                }
            }
        }
    }
    format!("bootstrap завершился с кодом {status}")
}

fn bootstrap_command(app: &AppHandle, action: &str) -> Result<Command, String> {
    let resources = resource_dir(app)?;

    #[cfg(target_os = "macos")]
    let mut command = {
        let mut value = Command::new("/bin/bash");
        value.arg(resources.join("bootstrap.sh"));
        value
    };

    #[cfg(target_os = "windows")]
    let mut command = {
        use std::os::windows::process::CommandExt;

        let mut value = Command::new("powershell.exe");
        value.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]);
        value.arg(resources.join("runtime/installers/windows/app/bootstrap.ps1"));
        value.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
        value
    };

    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    let mut command = {
        let mut value = Command::new("/bin/sh");
        value.arg(resources.join("runtime/installers/linux/install.sh"));
        value
    };

    command
        .env("LES_TAURI_SHELL", "1")
        .env("LES_TAURI_ACTION", action)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    Ok(command)
}

fn run_bootstrap(app: &AppHandle, action: &str) -> Result<(), String> {
    let status = bootstrap_command(app, action)?
        .status()
        .map_err(|error| format!("не удалось запустить bootstrap: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(bootstrap_failure_message(&status))
    }
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn show_error(app: &AppHandle, message: &str) {
    if let Some(window) = app.get_webview_window("main") {
        let safe = message
            .replace('&', "&amp;")
            .replace('<', "&lt;")
            .replace('>', "&gt;")
            .replace('\\', "\\\\")
            .replace('`', "\\`")
            .replace("${", "\\${")
            .replace('\n', "<br>");
        let _ = window.eval(format!(
            "document.querySelector('main').innerHTML = `<div class='mark'>!</div><h1>ЛЕС не запустился</h1><p>{safe}</p>`;"
        ));
    }
}

fn boot_and_navigate(app: AppHandle) {
    thread::spawn(move || {
        if !ui_ready(&app) {
            if let Err(error) = run_bootstrap(&app, "start") {
                show_error(&app, &error);
                return;
            }
        }

        let deadline = Instant::now() + Duration::from_secs(900);
        while Instant::now() < deadline {
            if ui_ready(&app) {
                if let Some(window) = app.get_webview_window("main") {
                    let (ui_url, _) = runtime_urls(&app);
                    match ui_url.parse::<Url>() {
                        Ok(url) => {
                            let _ = window.navigate(url);
                            show_main(&app);
                        }
                        Err(error) => show_error(&app, &error.to_string()),
                    }
                }
                return;
            }
            thread::sleep(Duration::from_secs(1));
        }
        show_error(&app, "службы не ответили за 15 минут; откройте журнал bootstrap");
    });
}

fn run_action(app: AppHandle, action: &'static str) {
    thread::spawn(move || {
        if let Err(error) = run_bootstrap(&app, action) {
            show_error(&app, &error);
            return;
        }
        if action == "restart" {
            boot_and_navigate(app);
        }
    });
}

fn install_tray(app: &tauri::App) -> tauri::Result<()> {
    let open = MenuItem::with_id(app, "open", "Открыть Совушку", true, None::<&str>)?;
    let restart = MenuItem::with_id(app, "restart", "Перезапустить службы", true, None::<&str>)?;
    let stop = MenuItem::with_id(app, "stop", "Остановить службы", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Выход", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &restart, &stop, &quit])?;
    let mut tray = TrayIconBuilder::new().menu(&menu).on_menu_event(|app, event| {
        match event.id.as_ref() {
            "open" => show_main(app),
            "restart" => run_action(app.clone(), "restart"),
            "stop" => run_action(app.clone(), "stop"),
            "quit" => app.exit(0),
            _ => {}
        }
    });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            install_tray(app)?;
            boot_and_navigate(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running LES Tauri shell");
}
