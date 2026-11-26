//! Platform-independent LocalIpcTransport trait + authenticated local loopback/Named-Pipe descriptor (DEC-008, T07).
//! The 256-bit per-run Core authentication secret lives strictly inside Rust broker memory and is NEVER exposed to WebView.

use rand::RngCore;
use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IpcTransportKind {
    WindowsNamedPipe { pipe_name: String },
    AuthenticatedLoopback { base_url: String },
}

pub trait LocalIpcTransport: Send + Sync {
    fn kind(&self) -> &IpcTransportKind;
    fn base_url(&self) -> &str;
    fn verify_token(&self, candidate: &str) -> bool;
    fn bearer_header_value(&self) -> String;
}

pub struct AuthenticatedLocalTransport {
    kind: IpcTransportKind,
    base_url: String,
    secret_token: String,
}

impl fmt::Debug for AuthenticatedLocalTransport {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("AuthenticatedLocalTransport")
            .field("kind", &self.kind)
            .field("base_url", &self.base_url)
            .field("secret_token", &"[REDACTED]")
            .finish()
    }
}

impl AuthenticatedLocalTransport {
    /// Generate a cryptographically random 256-bit (64 hex chars) per-run token.
    pub fn generate_random_token() -> String {
        let mut bytes = [0u8; 32];
        rand::rngs::OsRng.fill_bytes(&mut bytes);
        let mut out = String::with_capacity(64);
        for b in bytes {
            out.push_str(&format!("{b:02x}"));
        }
        out
    }

    pub fn new_loopback(port: u16, secret_token: String) -> Result<Self, &'static str> {
        if secret_token.len() < 32 {
            return Err("IPC secret token must have at least 32 characters (>= 256-bit).");
        }
        let base_url = format!("http://127.0.0.1:{port}");
        Ok(Self {
            kind: IpcTransportKind::AuthenticatedLoopback {
                base_url: base_url.clone(),
            },
            base_url,
            secret_token,
        })
    }

    #[cfg(windows)]
    pub fn windows_named_pipe_path(session_nonce: &str) -> String {
        format!(r"\\.\pipe\jarvis-core-{session_nonce}")
    }
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff: u8 = 0;
    for (&x, &y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
}

impl LocalIpcTransport for AuthenticatedLocalTransport {
    fn kind(&self) -> &IpcTransportKind {
        &self.kind
    }

    fn base_url(&self) -> &str {
        &self.base_url
    }

    fn verify_token(&self, candidate: &str) -> bool {
        constant_time_eq(self.secret_token.as_bytes(), candidate.as_bytes())
    }

    fn bearer_header_value(&self) -> String {
        format!("Bearer {}", self.secret_token)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn random_token_has_256_bit_hex_length_and_redacts_debug() {
        let token = AuthenticatedLocalTransport::generate_random_token();
        assert_eq!(token.len(), 64);

        let transport = AuthenticatedLocalTransport::new_loopback(47123, token.clone()).unwrap();
        assert!(transport.verify_token(&token));
        assert!(!transport.verify_token("wrong-token"));

        let dbg = format!("{transport:?}");
        assert!(!dbg.contains(&token), "Debug output MUST NOT leak IPC token");
        assert!(dbg.contains("[REDACTED]"));
    }

    #[test]
    fn rejects_weak_token() {
        let err = AuthenticatedLocalTransport::new_loopback(47123, "short".to_string());
        assert!(err.is_err());
    }
}
