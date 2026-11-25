#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_updater::UpdaterExt;

struct Sidecar {
    child: Mutex<Option<CommandChild>>,
}

/// 选一个空闲端口：先绑定 0 让系统分配，再释放给 sidecar 使用。
/// 固定 8788 在桌面端会与用户已经跑着的开发服务冲突，启动后表现为空白页。
fn pick_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8788)
}

/// 真正等 `/api/health` 返回 2xx，而不是只等端口可连接。
/// uvicorn 监听后到 lifespan 完成之间还有初始化，提前加载页面会拿到 503。
fn wait_until_ready(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let req = "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n";
            if stream.write_all(req.as_bytes()).is_ok() {
                let mut buf = String::new();
                if stream.read_to_string(&mut buf).is_ok() && buf.starts_with("HTTP/1.1 200") {
                    return true;
                }
            }
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

/// PyInstaller onefile 启动后是「bootloader 父进程 + 真实子进程」。
/// 只 kill bootloader 会把真实进程留成孤儿，用户关了窗口后台还在占端口。
fn stop_sidecar(child: tauri_plugin_shell::process::CommandChild) {
    let pid = child.pid();
    #[cfg(unix)]
    {
        let _ = std::process::Command::new("pkill")
            .args(["-TERM", "-P", &pid.to_string()])
            .status();
        let _ = child.kill();
        std::thread::sleep(Duration::from_millis(500));
        let _ = std::process::Command::new("pkill")
            .args(["-KILL", "-P", &pid.to_string()])
            .status();
    }
    #[cfg(windows)]
    {
        let _ = std::process::Command::new("taskkill")
            .args(["/T", "/F", "/PID", &pid.to_string()])
            .status();
        let _ = child.kill();
    }
    #[cfg(not(any(unix, windows)))]
    {
        let _ = child.kill();
    }
}


/// 返回给前端的更新探测结果。只暴露版本与说明，不把签名/下载地址透出去。
#[derive(Serialize)]
struct UpdateInfo {
    available: bool,
    current: String,
    version: Option<String>,
    notes: Option<String>,
    date: Option<String>,
}

#[tauri::command]
async fn check_update(app: tauri::AppHandle) -> Result<UpdateInfo, String> {
    let current = app.package_info().version.to_string();
    let updater = app.updater().map_err(|e| format!("更新器初始化失败: {e}"))?;
    match updater.check().await {
        Ok(Some(update)) => Ok(UpdateInfo {
            available: true,
            current,
            version: Some(update.version.clone()),
            notes: update.body.clone(),
            date: update.date.map(|d| d.to_string()),
        }),
        Ok(None) => Ok(UpdateInfo {
            available: false,
            current,
            version: None,
            notes: None,
            date: None,
        }),
        Err(e) => Err(format!("检查更新失败: {e}")),
    }
}

/// 下载并安装更新，然后重启自身。Linux AppImage 可直接自替换；
/// `.deb` 由包管理器接管，普通用户权限不足时应引导用户走 apt。
#[tauri::command]
async fn install_update(app: tauri::AppHandle) -> Result<(), String> {
    let updater = app.updater().map_err(|e| format!("更新器初始化失败: {e}"))?;
    let update = updater
        .check()
        .await
        .map_err(|e| format!("检查更新失败: {e}"))?
        .ok_or_else(|| "当前已是最新版本".to_string())?;
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(|e| format!("下载或安装更新失败: {e}"))?;
    app.restart();
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![check_update, install_update])
        .manage(Sidecar { child: Mutex::new(None) })
        .setup(|app| {
            let port = pick_port();
            let sidecar = app.shell().sidecar("moneyhelper-server")?;
            let (mut rx, child) = sidecar
                .env("MONEYHELPER_NO_BROWSER", "1")
                .env("PORT", port.to_string())
                .spawn()?;
            *app.state::<Sidecar>().child.lock().unwrap() = Some(child);

            // 必须持续消费 sidecar 的 stdout/stderr。直接丢接收端会让子进程
            // 写日志时拿到断开的管道，PyInstaller 的启动错误也会被吞掉。
            tauri::async_runtime::spawn(async move {
                use tauri_plugin_shell::process::CommandEvent;
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                            print!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[sidecar] exited: {:?}", payload);
                            break;
                        }
                        _ => {}
                    }
                }
            });

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let ready = wait_until_ready(port, Duration::from_secs(90));
                if !ready {
                    eprintln!("sidecar 未在 90 秒内就绪，仍尝试打开页面");
                }
                let url = format!("http://127.0.0.1:{port}/");
                let parsed = match url.parse() {
                    Ok(u) => u,
                    Err(e) => {
                        eprintln!("无效的服务地址 {url}: {e}");
                        return;
                    }
                };
                let window_handle = handle.clone();
                let _ = handle.run_on_main_thread(move || {
                    let _ = WebviewWindowBuilder::new(&window_handle, "main", WebviewUrl::External(parsed))
                        .title("Moneyhelper")
                        .inner_size(1280.0, 860.0)
                        .min_inner_size(960.0, 640.0)
                        .center()
                        .build();
                });
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Moneyhelper desktop")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(child) = app.state::<Sidecar>().child.lock().unwrap().take() {
                    stop_sidecar(child);
                }
            }
        });
}
