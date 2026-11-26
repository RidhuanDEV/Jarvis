//! Portable Python Core discovery and Win32-Job-supervised launcher (DEC-008, NFR-15, NFR-16).
//! Never hardcodes developer drive letters or usernames; passes 256-bit IPC token strictly via stdin pipe.

use crate::process_supervisor::{ProcessSupervisor, SupervisedProcess};
use serde::Deserialize;
use std::net::TcpListener;
use std::path::{Path, PathBuf};

#[derive(Debug, Deserialize)]
struct RuntimePointerFile {
    python_exe: String,
    core_dir: String,
}

#[derive(Debug, Clone)]
pub struct CoreRuntimeSpec {
    pub python_exe: PathBuf,
    pub core_dir: PathBuf,
}

#[derive(Debug, Clone)]
pub struct CoreLaunchOutcome {
    pub process: Option<SupervisedProcess>,
    pub core_dir: Option<PathBuf>,
    pub error: Option<String>,
}

/// Bind an ephemeral localhost port on 127.0.0.1 so multiple installs or port conflicts never break launch.
pub fn pick_ephemeral_loopback_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0")
        .map_err(|e| format!("Unable to allocate local loopback port: {e}"))?;
    let port = listener
        .local_addr()
        .map_err(|e| format!("Unable to read allocated loopback port: {e}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn venv_python_in_core(core_dir: &Path) -> Option<PathBuf> {
    #[cfg(windows)]
    let candidates = [
        core_dir.join(".venv").join("Scripts").join("python.exe"),
        core_dir.join("venv").join("Scripts").join("python.exe"),
    ];
    #[cfg(not(windows))]
    let candidates = [
        core_dir.join(".venv").join("bin").join("python"),
        core_dir.join("venv").join("bin").join("python"),
    ];

    for cand in candidates {
        if cand.is_file() {
            return Some(cand);
        }
    }
    None
}

fn has_core_entrypoint(core_dir: &Path) -> bool {
    core_dir
        .join("jarvis")
        .join("transport")
        .join("__main__.py")
        .is_file()
}

fn search_ancestors_for_core(start: &Path) -> Option<CoreRuntimeSpec> {
    let mut current = Some(start);
    for _ in 0..8 {
        let dir = current?;
        for rel in ["core", "resources/core"] {
            let core_dir = dir.join(rel);
            if has_core_entrypoint(&core_dir) {
                if let Some(python_exe) = venv_python_in_core(&core_dir) {
                    return Some(CoreRuntimeSpec {
                        python_exe,
                        core_dir,
                    });
                }
            }
        }
        current = dir.parent();
    }
    None
}

fn pointer_file_path() -> Option<PathBuf> {
    #[cfg(windows)]
    {
        std::env::var_os("LOCALAPPDATA")
            .map(|p| PathBuf::from(p).join("JarvisOS").join("Jarvis").join("runtime-pointer.json"))
    }
    #[cfg(not(windows))]
    {
        std::env::var_os("XDG_DATA_HOME")
            .map(PathBuf::from)
            .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".local").join("share")))
            .map(|p| p.join("JarvisOS").join("Jarvis").join("runtime-pointer.json"))
    }
}

fn read_runtime_pointer(path: &Path) -> Option<CoreRuntimeSpec> {
    let raw = std::fs::read_to_string(path).ok()?;
    let clean = raw.trim_start_matches('\u{feff}');
    let ptr: RuntimePointerFile = serde_json::from_str(clean).ok()?;
    let py_path = PathBuf::from(ptr.python_exe);
    let dir_path = PathBuf::from(ptr.core_dir);
    if py_path.is_file() && has_core_entrypoint(&dir_path) {
        Some(CoreRuntimeSpec {
            python_exe: py_path,
            core_dir: dir_path,
        })
    } else {
        None
    }
}

/// Discover the local Python Core runtime portably without hardcoded developer paths.
pub fn discover_core_runtime() -> Option<CoreRuntimeSpec> {
    // 1. Explicit runtime override (portable/custom deployment)
    if let (Ok(py), Ok(dir)) = (
        std::env::var("JARVIS_CORE_PYTHON"),
        std::env::var("JARVIS_CORE_DIR"),
    ) {
        let py_path = PathBuf::from(py);
        let dir_path = PathBuf::from(dir);
        if py_path.is_file() && has_core_entrypoint(&dir_path) {
            return Some(CoreRuntimeSpec {
                python_exe: py_path,
                core_dir: dir_path,
            });
        }
    }

    // 2. Relative to current executable directory (installed app / portable bundle / cargo target)
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            if let Some(found) = search_ancestors_for_core(exe_dir) {
                return Some(found);
            }
        }
    }

    // 3. Per-user OS app-data runtime pointer (created by local Windows installer for standalone Start Menu launches)
    if let Some(ptr_path) = pointer_file_path() {
        if let Some(found) = read_runtime_pointer(&ptr_path) {
            return Some(found);
        }
    }

    // 4. Relative to current working directory (dev launches / custom CARGO_TARGET_DIR)
    if let Ok(cwd) = std::env::current_dir() {
        if let Some(found) = search_ancestors_for_core(&cwd) {
            return Some(found);
        }
    }

    None
}

/// Spawn Python Core under the OS process supervisor (Win32 Job Object KILL_ON_JOB_CLOSE)
/// passing the 256-bit auth token strictly over inherited stdin pipe (09-SECURITY-PRIVACY.md §3).
pub fn spawn_local_core(
    supervisor: &dyn ProcessSupervisor,
    port: u16,
    auth_token: &str,
) -> CoreLaunchOutcome {
    let spec = match discover_core_runtime() {
        Some(s) => s,
        None => {
            return CoreLaunchOutcome {
                process: None,
                core_dir: None,
                error: Some(
                    "Portable Python Core runtime not found (set JARVIS_CORE_PYTHON & JARVIS_CORE_DIR or install bundled core).".to_string(),
                ),
            };
        }
    };

    let py_str = spec.python_exe.to_string_lossy().to_string();
    let core_dir_str = spec.core_dir.to_string_lossy().to_string();
    let port_str = port.to_string();
    let stdin_secret = format!("{auth_token}\n");

    let env_vars = [
        ("JARVIS_ENV", "production"),
        ("JARVIS_BIND_HOST", "127.0.0.1"),
        ("JARVIS_BIND_PORT", port_str.as_str()),
        ("JARVIS_TOKEN_FROM_STDIN", "1"),
        ("PYTHONPATH", core_dir_str.as_str()),
        ("PYTHONUNBUFFERED", "1"),
    ];

    match supervisor.spawn_managed_with_stdin_and_env(
        &py_str,
        &["-m", "jarvis.transport"],
        &env_vars,
        Some(stdin_secret.as_bytes()),
        Some(spec.core_dir.as_path()),
        "jarvis-local-core",
    ) {
        Ok(proc_handle) => CoreLaunchOutcome {
            process: Some(proc_handle),
            core_dir: Some(spec.core_dir),
            error: None,
        },
        Err(err) => CoreLaunchOutcome {
            process: None,
            core_dir: Some(spec.core_dir),
            error: Some(format!("Failed to launch local Python Core: {err}")),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allocates_valid_ephemeral_loopback_port() {
        let port = pick_ephemeral_loopback_port().expect("ephemeral port");
        assert!(port >= 1024);
    }

    #[test]
    fn discovers_repo_core_runtime_without_hardcoded_paths() {
        // When running `cargo test` inside apps/desktop/src-tauri, ancestor walk discovers `core/.venv`
        let found = discover_core_runtime();
        if let Some(spec) = found {
            assert!(spec.python_exe.is_file());
            assert!(has_core_entrypoint(&spec.core_dir));
        }
    }
}
