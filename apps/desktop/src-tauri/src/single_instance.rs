//! Single-instance desktop guard preventing WebView2 EBWebView lock collisions (HRESULT 0x800700AA).
//! When a second instance is launched while J.A.R.V.I.S. is already running, it restores & focuses
//! the active desktop window cleanly instead of crashing on WebView2 profile lock.

#[cfg(windows)]
mod imp {
    use windows_sys::Win32::Foundation::{CloseHandle, GetLastError, ERROR_ALREADY_EXISTS, HANDLE};
    use windows_sys::Win32::System::Threading::CreateMutexW;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        FindWindowW, SetForegroundWindow, ShowWindow, SW_RESTORE,
    };

    pub struct SingleInstanceGuard {
        handle: HANDLE,
    }

    fn to_wide_null(s: &str) -> Vec<u16> {
        s.encode_utf16().chain(std::iter::once(0)).collect()
    }

    impl SingleInstanceGuard {
        pub fn acquire(mutex_name: &str, existing_window_title: &str) -> Option<Self> {
            let wide_name = to_wide_null(mutex_name);
            // SAFETY: Standard Win32 CreateMutexW with null security attributes and null-terminated UTF-16 name.
            let handle = unsafe { CreateMutexW(std::ptr::null(), 0, wide_name.as_ptr()) };
            if handle.is_null() {
                // Fail-open if mutex creation itself fails unexpectedly so app can still start
                return Some(Self { handle });
            }
            // SAFETY: Immediately read Win32 thread-local error after CreateMutexW.
            let err = unsafe { GetLastError() };
            if err == ERROR_ALREADY_EXISTS {
                unsafe { CloseHandle(handle) };
                focus_existing_window(existing_window_title);
                return None;
            }
            Some(Self { handle })
        }
    }

    fn focus_existing_window(title: &str) {
        let wide_title = to_wide_null(title);
        // SAFETY: FindWindowW + ShowWindow + SetForegroundWindow with null-terminated UTF-16 title.
        unsafe {
            let hwnd = FindWindowW(std::ptr::null(), wide_title.as_ptr());
            if !hwnd.is_null() {
                ShowWindow(hwnd, SW_RESTORE);
                SetForegroundWindow(hwnd);
            }
        }
    }

    impl Drop for SingleInstanceGuard {
        fn drop(&mut self) {
            if !self.handle.is_null() {
                unsafe { CloseHandle(self.handle) };
                self.handle = std::ptr::null_mut();
            }
        }
    }
}

#[cfg(not(windows))]
mod imp {
    pub struct SingleInstanceGuard;

    impl SingleInstanceGuard {
        pub fn acquire(_mutex_name: &str, _existing_window_title: &str) -> Option<Self> {
            Some(Self)
        }
    }
}

pub use imp::SingleInstanceGuard;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[cfg(windows)]
    fn second_acquire_on_same_mutex_returns_none_and_releases_on_drop() {
        let name = format!("Local\\JARVIS_TEST_MUTEX_{}", std::process::id());
        let first = SingleInstanceGuard::acquire(&name, "Nonexistent-Test-Window");
        assert!(first.is_some());

        let second = SingleInstanceGuard::acquire(&name, "Nonexistent-Test-Window");
        assert!(
            second.is_none(),
            "Second instance must be blocked cleanly while first holds single-instance mutex"
        );

        drop(first);
        let third = SingleInstanceGuard::acquire(&name, "Nonexistent-Test-Window");
        assert!(
            third.is_some(),
            "Mutex must be acquirable again immediately after first guard drops"
        );
    }
}
