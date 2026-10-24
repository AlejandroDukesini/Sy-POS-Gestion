// POS-PY para Windows: ventana Tauri + backend Python empaquetado (pospy-server.exe).
//
// Ciclo de vida:
//  1. Se muestra una pantalla de carga local (ui/index.html).
//  2. Se elige un puerto libre en 127.0.0.1 y se inicia pospy-server.exe con la carpeta de datos del
//     usuario (%APPDATA%\com.pospy.app\data), un código de instalación aleatorio y el PID de esta app.
//  3. Cuando /api/health responde, la ventana navega a la interfaz servida por el backend.
//  4. Al cerrar la aplicación se detiene el backend; si esta aplicación termina de forma inesperada,
//     el backend detecta que el proceso padre desapareció y se cierra solo (--parent-pid).
// La interfaz no usa IPC de Tauri: habla con el backend local por HTTP, igual que en la web.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent, Url, WebviewUrl, WebviewWindowBuilder};

struct Backend(Mutex<Option<Child>>);

fn free_port() -> std::io::Result<u16> {
    Ok(TcpListener::bind("127.0.0.1:0")?.local_addr()?.port())
}

fn setup_code() -> String {
    let mut bytes = [0u8; 6];
    getrandom::getrandom(&mut bytes).expect("generador aleatorio del sistema");
    let hex: String = bytes.iter().map(|b| format!("{:02X}", b)).collect();
    format!("{}-{}-{}", &hex[0..4], &hex[4..8], &hex[8..12])
}

fn healthy(port: u16) -> bool {
    let Ok(mut stream) = TcpStream::connect_timeout(&([127, 0, 0, 1], port).into(), Duration::from_millis(500)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    if stream.write_all(b"GET /api/health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n").is_err() {
        return false;
    }
    let mut response = String::new();
    let _ = stream.read_to_string(&mut response);
    response.starts_with("HTTP/1.1 200") || response.starts_with("HTTP/1.0 200")
}

fn server_path() -> PathBuf {
    let exe = std::env::current_exe().expect("ruta del ejecutable");
    exe.parent().expect("carpeta del ejecutable").join("pospy-server.exe")
}

fn show_error(window: &tauri::WebviewWindow, message: &str) {
    let safe = message.replace('\\', "\\\\").replace('`', "'").replace('$', "");
    let _ = window.eval(&format!(
        "document.querySelector('main').innerHTML = `<h1 style=\"font-size:24px;color:#991b1b\">No se pudo iniciar POS-PY</h1>\
         <p>{safe}</p><p>Revise el registro en %APPDATA%\\\\com.pospy.app\\\\data\\\\logs\\\\pospy.log</p>`;"
    ));
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let window = WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
                .title("POS-PY")
                .inner_size(1366.0, 860.0)
                .min_inner_size(900.0, 600.0)
                .maximized(true)
                .build()?;

            let data_dir = app.path().app_data_dir()?.join("data");
            std::fs::create_dir_all(&data_dir)?;
            let port = free_port()?;
            let code = setup_code();
            let mut command = Command::new(server_path());
            command
                .args(["--host", "127.0.0.1", "--port", &port.to_string(), "--desktop"])
                .arg("--data-dir")
                .arg(&data_dir)
                .arg("--parent-pid")
                .arg(std::process::id().to_string())
                .env("POS_SETUP_CODE", &code);
            #[cfg(windows)]
            {
                use std::os::windows::process::CommandExt;
                command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW: sin consola visible
            }
            match command.spawn() {
                Ok(child) => *app.state::<Backend>().0.lock().unwrap() = Some(child),
                Err(err) => {
                    show_error(&window, &format!("No se encontró o no se pudo ejecutar pospy-server.exe ({err})."));
                    return Ok(());
                }
            }

            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let started = Instant::now();
                let window = handle.get_webview_window("main").expect("ventana principal");
                loop {
                    if healthy(port) {
                        let url = Url::parse(&format!("http://127.0.0.1:{port}/#setup={code}")).expect("URL local");
                        let _ = window.navigate(url);
                        break;
                    }
                    let exited = {
                        let state = handle.state::<Backend>();
                        let mut guard = state.0.lock().unwrap();
                        guard.as_mut().and_then(|c| c.try_wait().ok().flatten())
                    };
                    if let Some(status) = exited {
                        show_error(&window, &format!("El servidor local terminó al iniciar ({status})."));
                        break;
                    }
                    if started.elapsed() > Duration::from_secs(90) {
                        show_error(&window, "El servidor local no respondió en 90 segundos.");
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(300));
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error al construir la aplicación")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<Backend>().0.lock().unwrap().take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        });
}
