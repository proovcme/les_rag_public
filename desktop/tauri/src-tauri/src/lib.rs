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
use serde_json::{json, Value};

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

#[cfg(target_os = "windows")]
fn endpoint_responds(url: &str) -> bool {
    let Ok(parsed) = url.parse::<Url>() else { return false; };
    let Some(host) = parsed.host_str() else { return false; };
    let Some(port) = parsed.port_or_known_default() else { return false; };
    let Ok(addr) = format!("{host}:{port}").parse::<SocketAddr>() else { return false; };
    TcpStream::connect_timeout(&addr, Duration::from_millis(450)).is_ok()
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
fn windows_state_root() -> Option<PathBuf> {
    std::env::var_os("LES_WINDOWS_STATE_ROOT")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("LOCALAPPDATA").map(|path| PathBuf::from(path).join("LES")))
}

#[cfg(target_os = "windows")]
fn bootstrap_status_path() -> Option<PathBuf> {
    windows_state_root().map(|root| root.join("logs/bootstrap-status.json"))
}

#[cfg(target_os = "windows")]
fn read_bootstrap_status() -> Value {
    bootstrap_status_path()
        .and_then(|path| std::fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str(text.trim_start_matches('\u{feff}')).ok())
        .unwrap_or_else(|| json!({
            "state": "running",
            "phase": "bootstrap",
            "message": "Проверяю эту машину"
        }))
}

#[cfg(not(target_os = "windows"))]
fn read_bootstrap_status() -> Value {
    json!({"state": "ready", "phase": "ready", "message": "ЛЕС готов"})
}

#[cfg(target_os = "windows")]
fn resolve_windows_program(name: &str, candidates: &[PathBuf]) -> Option<PathBuf> {
    let path = Command::new("where.exe")
        .arg(name)
        .output()
        .ok()
        .filter(|output| output.status.success())
        .and_then(|output| {
            String::from_utf8_lossy(&output.stdout)
                .lines()
                .map(str::trim)
                .find(|line| !line.is_empty())
                .map(PathBuf::from)
        });
    path.or_else(|| candidates.iter().find(|path| path.is_file()).cloned())
}

#[cfg(target_os = "windows")]
fn windows_programs() -> (Option<PathBuf>, Option<PathBuf>) {
    let local = std::env::var_os("LOCALAPPDATA").map(PathBuf::from);
    let program_files = std::env::var_os("ProgramFiles").map(PathBuf::from);
    let ollama_candidates = [
        local
            .as_ref()
            .map(|path| path.join("Programs/Ollama/ollama.exe"))
            .unwrap_or_default(),
        program_files
            .as_ref()
            .map(|path| path.join("Ollama/ollama.exe"))
            .unwrap_or_default(),
    ];
    let docker_candidates = [program_files
        .as_ref()
        .map(|path| path.join("Docker/Docker/resources/bin/docker.exe"))
        .unwrap_or_default()];
    (
        resolve_windows_program("ollama.exe", &ollama_candidates),
        resolve_windows_program("docker.exe", &docker_candidates),
    )
}

#[cfg(target_os = "windows")]
fn read_dotenv_value(path: &std::path::Path, key: &str) -> String {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|text| {
            text.lines()
                .rev()
                .find_map(|line| line.strip_prefix(&format!("{key}=")))
                .map(|value| value.trim().trim_matches(['\"', '\'']).to_string())
        })
        .unwrap_or_default()
}

#[cfg(target_os = "windows")]
fn write_dotenv_values(path: &std::path::Path, changes: &[(&str, &str)]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let existing = std::fs::read_to_string(path).unwrap_or_default();
    let mut lines: Vec<String> = existing.lines().map(str::to_string).collect();
    for (key, value) in changes {
        let prefix = format!("{key}=");
        lines.retain(|line| !line.starts_with(&prefix));
        lines.push(format!("{key}={value}"));
    }
    let body = format!("{}\n", lines.join("\n"));
    std::fs::write(path, body).map_err(|error| error.to_string())
}

#[tauri::command]
fn setup_snapshot(app: AppHandle) -> Value {
    #[cfg(target_os = "windows")]
    {
        let (ollama, docker) = windows_programs();
        let models = ollama
            .as_ref()
            .and_then(|program| Command::new(program).arg("list").output().ok())
            .filter(|output| output.status.success())
            .map(|output| {
                String::from_utf8_lossy(&output.stdout)
                    .lines()
                    .skip(1)
                    .filter_map(|line| line.split_whitespace().next())
                    .map(str::to_string)
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let ollama_running = ollama
            .as_ref()
            .and_then(|program| Command::new(program).arg("list").status().ok())
            .is_some_and(|status| status.success());
        let docker_running = docker
            .as_ref()
            .and_then(|program| Command::new(program).arg("info").status().ok())
            .is_some_and(|status| status.success());
        let selected_model = windows_state_root()
            .map(|root| root.join(".env"))
            .map(|path| read_dotenv_value(&path, "OLLAMA_MODEL"))
            .unwrap_or_default();
        let selected_present = !selected_model.is_empty() && models.iter().any(|item| item == &selected_model);
        let embedding_present = models.iter().any(|item| item == "bge-m3" || item == "bge-m3:latest");
        let status = read_bootstrap_status();
        return json!({
            "platform": "windows",
            "bootstrap": status,
            "ollama": {"installed": ollama.is_some(), "running": ollama_running},
            "docker": {"installed": docker.is_some(), "running": docker_running},
            "qdrant": {"running": endpoint_responds("http://127.0.0.1:6333/collections")},
            "models": models,
            "selected_model": selected_model,
            "selected_model_present": selected_present,
            "embedding_present": embedding_present,
            "recommended_model": "qwen3.5:9b",
            "recommended_embedding": "bge-m3:latest",
            "can_start": ollama_running && docker_running && selected_present && embedding_present,
            "ui_ready": ui_ready(&app),
        });
    }
    #[cfg(not(target_os = "windows"))]
    json!({"platform": std::env::consts::OS, "bootstrap": read_bootstrap_status(), "ui_ready": ui_ready(&app)})
}

#[tauri::command]
fn install_setup_component(component: String) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        let (package, title) = match component.as_str() {
            "ollama" => ("Ollama.Ollama", "Ollama"),
            "docker" => ("Docker.DockerDesktop", "Docker Desktop"),
            _ => return Err("неизвестный компонент".to_string()),
        };
        let status = Command::new("winget.exe")
            .args([
                "install",
                "--id",
                package,
                "-e",
                "--source",
                "winget",
                "--accept-source-agreements",
                "--accept-package-agreements",
            ])
            .status()
            .map_err(|_| format!("winget недоступен. Установите {title} по ссылке в мастере"))?;
        return status
            .success()
            .then_some(())
            .ok_or_else(|| format!("winget не смог установить {title}"));
    }
    #[cfg(not(target_os = "windows"))]
    {
        let _ = component;
        Err("мастер компонентов доступен только в Windows".to_string())
    }
}

#[tauri::command]
fn open_setup_link(kind: String) -> Result<(), String> {
    let url = match kind.as_str() {
        "ollama" => "https://ollama.com/download/windows",
        "models" => "https://ollama.com/library",
        "docker" => "https://www.docker.com/products/docker-desktop/",
        _ => return Err("неизвестная ссылка".to_string()),
    };
    #[cfg(target_os = "windows")]
    let status = Command::new("cmd.exe").args(["/c", "start", "", url]).status();
    #[cfg(target_os = "macos")]
    let status = Command::new("open").arg(url).status();
    #[cfg(all(not(target_os = "windows"), not(target_os = "macos")))]
    let status = Command::new("xdg-open").arg(url).status();
    status
        .map_err(|error| error.to_string())?
        .success()
        .then_some(())
        .ok_or_else(|| "не удалось открыть ссылку".to_string())
}

#[cfg(target_os = "windows")]
fn bootstrap_launcher_logs() -> Option<(PathBuf, PathBuf)> {
    windows_state_root().map(|root| {
        let logs = root.join("logs");
        (logs.join("tauri-bootstrap.out.log"), logs.join("tauri-bootstrap.err.log"))
    })
}

#[cfg(target_os = "windows")]
fn powershell_file_arg(path: PathBuf) -> String {
    let raw = path.to_string_lossy();
    raw.strip_prefix(r"\\?\").unwrap_or(&raw).to_string()
}

fn bootstrap_failure_message(status: &std::process::ExitStatus) -> String {
    #[cfg(target_os = "windows")]
    if let Some(path) = bootstrap_status_path() {
        if let Ok(text) = std::fs::read_to_string(&path) {
            if let Ok(payload) = serde_json::from_str::<serde_json::Value>(
                text.trim_start_matches('\u{feff}'),
            ) {
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
    #[cfg(target_os = "windows")]
    if let Some((_, stderr_path)) = bootstrap_launcher_logs() {
        if let Ok(stderr) = std::fs::read_to_string(&stderr_path) {
            let excerpt = stderr.trim_start_matches('\u{feff}').trim();
            if !excerpt.is_empty() {
                let tail = excerpt.chars().rev().take(1200).collect::<String>().chars().rev().collect::<String>();
                return format!("{tail}\nЖурнал: {}", stderr_path.display());
            }
        }
        return format!(
            "bootstrap завершился с кодом {status}\nЖурнал: {}",
            stderr_path.display()
        );
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
        value.arg(powershell_file_arg(
            resources.join("runtime/installers/windows/app/bootstrap.ps1"),
        ));
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
        .stdin(Stdio::null());
    #[cfg(target_os = "windows")]
    if let Some((stdout_path, stderr_path)) = bootstrap_launcher_logs() {
        if let Some(parent) = stdout_path.parent() {
            std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
        }
        let stdout = std::fs::File::create(stdout_path).map_err(|error| error.to_string())?;
        let stderr = std::fs::File::create(stderr_path).map_err(|error| error.to_string())?;
        command.stdout(Stdio::from(stdout)).stderr(Stdio::from(stderr));
    }
    #[cfg(not(target_os = "windows"))]
    command.stdout(Stdio::null()).stderr(Stdio::null());
    Ok(command)
}

fn run_bootstrap(app: &AppHandle, action: &str) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    if let Some(path) = bootstrap_status_path() {
        let _ = std::fs::remove_file(path);
    }
    let status = bootstrap_command(app, action)?
        .status()
        .map_err(|error| format!("не удалось запустить bootstrap: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err(bootstrap_failure_message(&status))
    }
}

fn setup_required() -> bool {
    read_bootstrap_status()
        .get("state")
        .and_then(Value::as_str)
        .is_some_and(|state| state == "setup_required")
}

fn show_setup(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        if let Ok(url) = Url::parse("tauri://localhost/index.html") {
            let _ = window.navigate(url);
        }
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[tauri::command]
fn save_setup_model(model: String) -> Result<(), String> {
    let model = model.trim();
    if model.is_empty() || model.contains(['\r', '\n', '=']) {
        return Err("выберите корректный тег установленной модели".to_string());
    }
    #[cfg(target_os = "windows")]
    {
        let path = windows_state_root()
            .ok_or_else(|| "не найден каталог состояния ЛЕС".to_string())?
            .join(".env");
        return write_dotenv_values(
            &path,
            &[
                ("LES_LLM_PROVIDER", "ollama"),
                ("OLLAMA_MODEL", model),
                ("LLM_MODEL", model),
            ],
        );
    }
    #[cfg(not(target_os = "windows"))]
    Err("выбор модели в мастере доступен только в Windows".to_string())
}

#[tauri::command]
fn start_from_setup(app: AppHandle, model: String) -> Result<(), String> {
    save_setup_model(model)?;
    boot_and_navigate(app);
    Ok(())
}

#[tauri::command]
fn retry_setup(app: AppHandle) {
    boot_and_navigate(app);
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
                eprintln!("LES bootstrap: {error}");
                show_setup(&app);
                return;
            }
            if setup_required() {
                show_setup(&app);
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
        show_setup(&app);
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
    let setup = MenuItem::with_id(app, "setup", "Настройка и справка", true, None::<&str>)?;
    let restart = MenuItem::with_id(app, "restart", "Перезапустить службы", true, None::<&str>)?;
    let stop = MenuItem::with_id(app, "stop", "Остановить службы", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Выход", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&open, &setup, &restart, &stop, &quit])?;
    let mut tray = TrayIconBuilder::new().menu(&menu).on_menu_event(|app, event| {
        match event.id.as_ref() {
            "open" => show_main(app),
            "setup" => show_setup(app),
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
        .invoke_handler(tauri::generate_handler![
            setup_snapshot,
            install_setup_component,
            open_setup_link,
            save_setup_model,
            start_from_setup,
            retry_setup,
        ])
        .setup(|app| {
            install_tray(app)?;
            boot_and_navigate(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running LES Tauri shell");
}
