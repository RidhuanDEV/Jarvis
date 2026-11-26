//! Platform-independent ProcessSupervisor trait + Windows Job Object KILL_ON_JOB_CLOSE (DEC-008, DEC-020, BR-AI-04, NFR-15).

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::Write;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeOwnershipMode {
    ManagedLocal,
    ExternalLocal,
    AuthorizedLan,
    CustomCompatible,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SupervisedProcess {
    pub pid: u32,
    pub ownership_mode: RuntimeOwnershipMode,
    pub label: String,
}

#[derive(Debug, Error)]
pub enum SupervisorError {
    #[error("BR-AI-04 ownership violation: cannot terminate external_local process (pid={0}) without explicit approval")]
    ExternalProcessProtected(u32),
    #[error("Failed to spawn supervised child process: {0}")]
    SpawnFailed(String),
    #[error("OS job object error: {0}")]
    JobObjectFailed(String),
    #[error("Process not found in supervisor registry: pid={0}")]
    NotFound(u32),
}

pub trait ProcessSupervisor: Send + Sync {
    fn spawn_managed(
        &self,
        program: &str,
        args: &[&str],
        label: &str,
    ) -> Result<SupervisedProcess, SupervisorError>;
    fn spawn_managed_with_stdin_and_env(
        &self,
        program: &str,
        args: &[&str],
        env_vars: &[(&str, &str)],
        stdin_payload: Option<&[u8]>,
        working_dir: Option<&Path>,
        label: &str,
    ) -> Result<SupervisedProcess, SupervisorError>;
    fn register_external(&self, pid: u32, label: &str) -> SupervisedProcess;
    fn terminate_if_allowed(
        &self,
        process: &SupervisedProcess,
        force_external_approved: bool,
    ) -> Result<(), SupervisorError>;
    fn is_alive(&self, pid: u32) -> bool;
    fn close_all_managed(&self) -> usize;
}

#[cfg(windows)]
mod win_job {
    use super::SupervisorError;
    use std::ffi::c_void;
    use std::mem::{size_of, zeroed};
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, TerminateJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Threading::{
        GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_SET_QUOTA,
        PROCESS_TERMINATE,
    };

    const STILL_ACTIVE: u32 = 259;

    pub struct WinJobHandle {
        raw: HANDLE,
    }

    // SAFETY: Win32 Job Object handles are process-global kernel objects safe to transfer/synchronize behind a Mutex.
    unsafe impl Send for WinJobHandle {}
    unsafe impl Sync for WinJobHandle {}

    impl WinJobHandle {
        pub fn create_kill_on_close() -> Result<Self, SupervisorError> {
            // SAFETY: Standard Win32 CreateJobObjectW with null security attrs and unnamed job.
            let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
            if handle.is_null() {
                return Err(SupervisorError::JobObjectFailed(
                    "CreateJobObjectW returned null".to_string(),
                ));
            }
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            // SAFETY: Pointer and byte size match JOBOBJECT_EXTENDED_LIMIT_INFORMATION exactly.
            let ok = unsafe {
                SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    (&info as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast::<c_void>(),
                    size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )
            };
            if ok == 0 {
                unsafe { CloseHandle(handle) };
                return Err(SupervisorError::JobObjectFailed(
                    "SetInformationJobObject(KILL_ON_JOB_CLOSE) failed".to_string(),
                ));
            }
            Ok(Self { raw: handle })
        }

        pub fn assign_pid(&self, pid: u32) -> Result<(), SupervisorError> {
            // SAFETY: Requesting minimal quota+terminate access for child process spawned by this broker.
            let proc_handle =
                unsafe { OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid) };
            if proc_handle.is_null() {
                return Err(SupervisorError::JobObjectFailed(format!(
                    "OpenProcess failed for pid={pid}"
                )));
            }
            let ok = unsafe { AssignProcessToJobObject(self.raw, proc_handle) };
            unsafe { CloseHandle(proc_handle) };
            if ok == 0 {
                return Err(SupervisorError::JobObjectFailed(format!(
                    "AssignProcessToJobObject failed for pid={pid}"
                )));
            }
            Ok(())
        }

        pub fn terminate_and_close(&mut self) {
            if !self.raw.is_null() {
                unsafe {
                    TerminateJobObject(self.raw, 1);
                    CloseHandle(self.raw);
                }
                self.raw = std::ptr::null_mut();
            }
        }
    }

    impl Drop for WinJobHandle {
        fn drop(&mut self) {
            self.terminate_and_close();
        }
    }

    pub fn is_pid_running(pid: u32) -> bool {
        let proc_handle = unsafe { OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid) };
        if proc_handle.is_null() {
            return false;
        }
        let mut exit_code: u32 = 0;
        let ok = unsafe { GetExitCodeProcess(proc_handle, &mut exit_code) };
        unsafe { CloseHandle(proc_handle) };
        ok != 0 && exit_code == STILL_ACTIVE
    }
}

pub struct NativeProcessSupervisor {
    managed: Mutex<HashMap<u32, Child>>,
    external: Mutex<HashMap<u32, SupervisedProcess>>,
    #[cfg(windows)]
    job: Mutex<Option<win_job::WinJobHandle>>,
}

impl NativeProcessSupervisor {
    pub fn new() -> Result<Self, SupervisorError> {
        Ok(Self {
            managed: Mutex::new(HashMap::new()),
            external: Mutex::new(HashMap::new()),
            #[cfg(windows)]
            job: Mutex::new(Some(win_job::WinJobHandle::create_kill_on_close()?)),
        })
    }
}

impl ProcessSupervisor for NativeProcessSupervisor {
    fn spawn_managed(
        &self,
        program: &str,
        args: &[&str],
        label: &str,
    ) -> Result<SupervisedProcess, SupervisorError> {
        self.spawn_managed_with_stdin_and_env(program, args, &[], None, None, label)
    }

    fn spawn_managed_with_stdin_and_env(
        &self,
        program: &str,
        args: &[&str],
        env_vars: &[(&str, &str)],
        stdin_payload: Option<&[u8]>,
        working_dir: Option<&Path>,
        label: &str,
    ) -> Result<SupervisedProcess, SupervisorError> {
        let mut cmd = Command::new(program);
        cmd.args(args)
            .stdin(if stdin_payload.is_some() {
                Stdio::piped()
            } else {
                Stdio::null()
            })
            .stdout(Stdio::null())
            .stderr(Stdio::null());

        if let Some(dir) = working_dir {
            cmd.current_dir(dir);
        }
        for (k, v) in env_vars {
            cmd.env(k, v);
        }

        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }

        let mut child = cmd
            .spawn()
            .map_err(|e| SupervisorError::SpawnFailed(e.to_string()))?;

        let pid = child.id();

        #[cfg(windows)]
        {
            let guard = self.job.lock().unwrap();
            if let Some(ref job) = *guard {
                if let Err(err) = job.assign_pid(pid) {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(err);
                }
            }
        }

        // Write secret token over inherited stdin pipe and immediately close pipe EOF
        if let Some(payload) = stdin_payload {
            if let Some(mut stdin) = child.stdin.take() {
                if let Err(err) = stdin.write_all(payload).and_then(|()| stdin.flush()) {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Err(SupervisorError::SpawnFailed(format!(
                        "Failed writing inherited stdin pipe: {err}"
                    )));
                }
            }
        }

        self.managed.lock().unwrap().insert(pid, child);
        Ok(SupervisedProcess {
            pid,
            ownership_mode: RuntimeOwnershipMode::ManagedLocal,
            label: label.to_string(),
        })
    }

    fn register_external(&self, pid: u32, label: &str) -> SupervisedProcess {
        let proc = SupervisedProcess {
            pid,
            ownership_mode: RuntimeOwnershipMode::ExternalLocal,
            label: label.to_string(),
        };
        self.external.lock().unwrap().insert(pid, proc.clone());
        proc
    }

    fn terminate_if_allowed(
        &self,
        process: &SupervisedProcess,
        force_external_approved: bool,
    ) -> Result<(), SupervisorError> {
        if process.ownership_mode != RuntimeOwnershipMode::ManagedLocal && !force_external_approved
        {
            return Err(SupervisorError::ExternalProcessProtected(process.pid));
        }

        if let Some(mut child) = self.managed.lock().unwrap().remove(&process.pid) {
            let _ = child.kill();
            let _ = child.wait();
            return Ok(());
        }
        Err(SupervisorError::NotFound(process.pid))
    }

    fn is_alive(&self, pid: u32) -> bool {
        if let Some(child) = self.managed.lock().unwrap().get_mut(&pid) {
            return matches!(child.try_wait(), Ok(None));
        }
        #[cfg(windows)]
        {
            win_job::is_pid_running(pid)
        }
        #[cfg(not(windows))]
        {
            let _ = pid;
            false
        }
    }

    fn close_all_managed(&self) -> usize {
        let mut guard = self.managed.lock().unwrap();
        let count = guard.len();
        for (_pid, mut child) in guard.drain() {
            let _ = child.kill();
            let _ = child.wait();
        }
        #[cfg(windows)]
        {
            if let Some(mut job) = self.job.lock().unwrap().take() {
                job.terminate_and_close();
            }
        }
        count
    }
}

impl Drop for NativeProcessSupervisor {
    fn drop(&mut self) {
        let _ = self.close_all_managed();
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{Duration, Instant};

    struct ChildGuard(Child);
    impl Drop for ChildGuard {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }

    #[test]
    #[cfg(windows)]
    fn managed_local_killed_within_5s_while_external_local_survives_untouched() {
        let supervisor = NativeProcessSupervisor::new().expect("supervisor init");

        // Spawn an independent external process NOT owned by JARVIS (simulating user's Ollama)
        let ext_child = Command::new("powershell.exe")
            .args(["-NoProfile", "-Command", "Start-Sleep -Seconds 30"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("spawn external mock");
        let ext_pid = ext_child.id();
        let _ext_guard = ChildGuard(ext_child);
        let ext_handle = supervisor.register_external(ext_pid, "external-mock-ollama");

        // Spawn a managed_local child inside the Win32 Job Object
        let managed = supervisor
            .spawn_managed(
                "powershell.exe",
                &["-NoProfile", "-Command", "Start-Sleep -Seconds 30"],
                "managed-mock-runtime",
            )
            .expect("spawn managed");

        assert!(supervisor.is_alive(managed.pid));
        assert!(supervisor.is_alive(ext_pid));

        // BR-AI-04: Attempting to terminate external_local without approval MUST fail
        let deny_err = supervisor.terminate_if_allowed(&ext_handle, false);
        assert!(matches!(
            deny_err,
            Err(SupervisorError::ExternalProcessProtected(p)) if p == ext_pid
        ));
        assert!(supervisor.is_alive(ext_pid));

        // NFR-15: Closing all managed workers terminates managed_local <= 5s and leaves external_local untouched
        let started = Instant::now();
        let closed = supervisor.close_all_managed();
        let elapsed = started.elapsed();

        assert_eq!(closed, 1);
        assert!(
            elapsed < Duration::from_secs(5),
            "Managed worker termination exceeded 5s NFR-15 budget: {elapsed:?}"
        );
        assert!(!supervisor.is_alive(managed.pid));
        assert!(
            supervisor.is_alive(ext_pid),
            "external_local process MUST remain alive after JARVIS closes managed workers"
        );
    }
}
