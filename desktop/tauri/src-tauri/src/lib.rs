use std::{
    io::{Read, Write},
    net::{SocketAddr, TcpStream},
    path::PathBuf,
    process::{Command, Stdio},
    sync::atomic::{AtomicBool, Ordering},
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
static LIFECYCLE_IN_FLIGHT: AtomicBool = AtomicBool::new(false);

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

#[cfg(target_os = "windows")]
fn windows_command(program: impl AsRef<std::ffi::OsStr>) -> Command {
    use std::os::windows::process::CommandExt;

    let mut command = Command::new(program);
    command.creation_flags(CREATE_NO_WINDOW).stdin(Stdio::null());
    command
}

struct LifecycleGuard;

impl LifecycleGuard {
    fn try_acquire() -> Option<Self> {
        LIFECYCLE_IN_FLIGHT
            .compare_exchange(false, true, Ordering::AcqRel, Ordering::Acquire)
            .ok()
            .map(|_| Self)
    }
}

impl Drop for LifecycleGuard {
    fn drop(&mut self) {
        LIFECYCLE_IN_FLIGHT.store(false, Ordering::Release);
    }
}

#[cfg(target_os = "windows")]
struct WindowsSingleInstanceGuard(*mut std::ffi::c_void);

#[cfg(target_os = "windows")]
impl WindowsSingleInstanceGuard {
    fn acquire() -> Result<Option<Self>, String> {
        use std::os::windows::ffi::OsStrExt;

        const ERROR_ALREADY_EXISTS: u32 = 183;
        let name = std::ffi::OsStr::new(r"Local\LES.Tauri.SingleInstance")
            .encode_wide()
            .chain(std::iter::once(0))
            .collect::<Vec<_>>();
        let handle = unsafe {
            CreateMutexW(
                std::ptr::null_mut(),
                0,
                name.as_ptr(),
            )
        };
        if handle.is_null() {
            return Err(std::io::Error::last_os_error().to_string());
        }
        let last_error = unsafe { GetLastError() };
        if last_error == ERROR_ALREADY_EXISTS {
            unsafe {
                CloseHandle(handle);
            }
            return Ok(None);
        }
        Ok(Some(Self(handle)))
    }
}

#[cfg(target_os = "windows")]
impl Drop for WindowsSingleInstanceGuard {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0);
        }
    }
}

#[cfg(target_os = "windows")]
#[link(name = "kernel32")]
extern "system" {
    fn CreateMutexW(
        mutex_attributes: *mut std::ffi::c_void,
        initial_owner: i32,
        name: *const u16,
    ) -> *mut std::ffi::c_void;
    fn GetLastError() -> u32;
    fn CloseHandle(handle: *mut std::ffi::c_void) -> i32;
}

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
    candidates
        .iter()
        .find(|path| path.is_file())
        .cloned()
        .or_else(|| {
            std::env::var_os("PATH").and_then(|path| {
                std::env::split_paths(&path)
                    .map(|directory| directory.join(name))
                    .find(|candidate| candidate.is_file())
            })
        })
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

#[tauri::command]
fn setup_snapshot(app: AppHandle) -> Value {
    #[cfg(target_os = "windows")]
    {
        let (ollama, docker) = windows_programs();
        let ollama_output = ollama
            .as_ref()
            .and_then(|program| {
                windows_command(program)
                    .arg("list")
                    .stderr(Stdio::null())
                    .output()
                    .ok()
            });
        let ollama_running = ollama_output
            .as_ref()
            .is_some_and(|output| output.status.success());
        let models = ollama_output
            .as_ref()
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
        let docker_running = docker
            .as_ref()
            .and_then(|program| {
                windows_command(program)
                    .arg("info")
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .status()
                    .ok()
            })
            .is_some_and(|status| status.success());
        let env_path = windows_state_root().map(|root| root.join(".env"));
        let configured_provider = env_path
            .as_ref()
            .map(|path| read_dotenv_value(path, "LES_LLM_PROVIDER"))
            .unwrap_or_default()
            .to_lowercase();
        let embedding_backend = env_path
            .as_ref()
            .map(|path| read_dotenv_value(path, "EMBED_BACKEND"))
            .unwrap_or_default()
            .to_lowercase();
        let ollama_embedding = models.iter().any(|item| item == "bge-m3" || item == "bge-m3:latest");
        let freetoken_running = endpoint_responds("http://127.0.0.1:1919/v1/models");
        let lemonade_running = endpoint_responds("http://127.0.0.1:13305/api/v1/models");
        let openai_configured = matches!(
            configured_provider.as_str(),
            "openai" | "openrouter" | "openai-compatible"
        );
        let status = read_bootstrap_status();
        let bootstrap_state = status.get("state").and_then(Value::as_str).unwrap_or("running");
        let ui_is_ready = ui_ready(&app);
        let core_ready = ui_is_ready || bootstrap_state == "ready";
        return json!({
            "platform": "windows",
            "bootstrap": status,
            "configured_provider": configured_provider,
            "providers": [
                {"id": "ollama", "label": "Ollama", "configured": configured_provider == "ollama", "installed": ollama.is_some(), "available": ollama_running},
                {"id": "freetoken", "label": "FreeToken", "configured": configured_provider == "freetoken", "installed": freetoken_running, "available": freetoken_running},
                {"id": "lemonade", "label": "Lemonade", "configured": configured_provider == "lemonade", "installed": lemonade_running, "available": lemonade_running},
                {"id": "openai-compatible", "label": "OpenAI-compatible", "configured": openai_configured, "installed": openai_configured, "available": openai_configured}
            ],
            "embeddings": [
                {"id": "ollama-bge-m3", "label": "Ollama · bge-m3", "configured": embedding_backend == "ollama" || configured_provider == "ollama" || configured_provider == "freetoken", "available": ollama_running && ollama_embedding},
                {"id": "lemonade", "label": "Lemonade embeddings", "configured": configured_provider == "lemonade", "available": lemonade_running}
            ],
            "docker": {"installed": docker.is_some(), "running": docker_running},
            "qdrant": {"running": endpoint_responds("http://127.0.0.1:6333/collections")},
            "models": models,
            "core_ready": core_ready,
            "ui_ready": ui_is_ready,
        });
    }
    #[cfg(not(target_os = "windows"))]
    json!({"platform": std::env::consts::OS, "bootstrap": read_bootstrap_status(), "ui_ready": ui_ready(&app)})
}

#[tauri::command]
fn open_setup_link(kind: String) -> Result<(), String> {
    let url = match kind.as_str() {
        "ollama" => "https://ollama.com/download/windows",
        "freetoken" => "https://github.com/FlashML-org/FreeToken",
        "lemonade" => "https://lemonade-server.ai/",
        "openai-compatible" => "https://platform.openai.com/docs/api-reference/introduction",
        "docker" => "https://www.docker.com/products/docker-desktop/",
        _ => return Err("неизвестная ссылка".to_string()),
    };
    #[cfg(target_os = "windows")]
    let status = windows_command("rundll32.exe")
        .args(["url.dll,FileProtocolHandler", url])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
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
        let mut value = windows_command("powershell.exe");
        value.args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]);
        value.arg(powershell_file_arg(
            resources.join("runtime/installers/windows/app/bootstrap.ps1"),
        ));
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
fn start_from_setup(app: AppHandle) -> Result<(), String> {
    schedule_boot_and_navigate(app)
        .then_some(())
        .ok_or_else(|| "Подготовка ЛЕС уже выполняется".to_string())
}

#[tauri::command]
fn retry_setup(app: AppHandle) -> Result<(), String> {
    schedule_boot_and_navigate(app)
        .then_some(())
        .ok_or_else(|| "Подготовка ЛЕС уже выполняется".to_string())
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
            "document.querySelector('main').innerHTML = `<div class='mark'>!</div><h1>Запуск остановлен</h1><p>{safe}</p><p>Откройте «Настройка» и повторите проверку после устранения указанной причины.</p>`;"
        ));
    }
}

fn wait_for_ui_and_navigate(app: &AppHandle) {
    let deadline = Instant::now() + Duration::from_secs(900);
    while Instant::now() < deadline {
        if ui_ready(app) {
            if let Some(window) = app.get_webview_window("main") {
                let (ui_url, _) = runtime_urls(app);
                match ui_url.parse::<Url>() {
                    Ok(url) => {
                        let _ = window.navigate(url);
                        show_main(app);
                    }
                    Err(error) => show_error(app, &error.to_string()),
                }
            }
            return;
        }
        thread::sleep(Duration::from_secs(1));
    }
    show_setup(app);
}

fn boot_and_navigate(app: &AppHandle) {
    if !ui_ready(app) {
        if run_bootstrap(app, "start").is_err() {
            show_setup(app);
            return;
        }
        if setup_required() {
            show_setup(app);
            return;
        }
    }
    wait_for_ui_and_navigate(app);
}

fn schedule_boot_and_navigate(app: AppHandle) -> bool {
    let Some(guard) = LifecycleGuard::try_acquire() else {
        return false;
    };
    thread::spawn(move || {
        let _guard = guard;
        boot_and_navigate(&app);
    });
    true
}

fn run_action(app: AppHandle, action: &'static str) {
    let Some(guard) = LifecycleGuard::try_acquire() else {
        return;
    };
    thread::spawn(move || {
        let _guard = guard;
        if let Err(error) = run_bootstrap(&app, action) {
            show_error(&app, &error);
            return;
        }
        if action == "restart" {
            wait_for_ui_and_navigate(&app);
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
    #[cfg(target_os = "windows")]
    let _single_instance = match WindowsSingleInstanceGuard::acquire() {
        Ok(Some(guard)) => guard,
        Ok(None) => return,
        Err(error) => {
            if let Some(root) = windows_state_root() {
                let logs = root.join("logs");
                let _ = std::fs::create_dir_all(&logs);
                let _ = std::fs::write(
                    logs.join("tauri-shell.err.log"),
                    format!("single-instance guard failed: {error}\n"),
                );
            }
            return;
        }
    };

    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            setup_snapshot,
            open_setup_link,
            start_from_setup,
            retry_setup,
        ])
        .setup(|app| {
            install_tray(app)?;
            schedule_boot_and_navigate(app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running LES Tauri shell");
}
