# Integration, Desktop Automation, IoT & Remote Design

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Windows adapter
Native allowlisted app registry: stable app_id, verified executable/app identifier, fixed allowed arguments, permitted actions, user grant. Launch via OS API, never shell evaluation. Core Audio endpoint for volume. File search in approved roots only, validate real path and opened handle; restrict rename within approved root and no overwrite. UI Automation for semantic control reading/invocation only on opted-in app/window; no coordinate click fallback by default, no password fields, no login bypass or arbitrary key injection. No elevation. If UAC, protected app, lock screen or unsupported UI appears, return unsupported and ask manual operation. OS sleep pauses active work; reconcile when resumed.

## 2. Screen and camera
R2 window-specific capture via OS API; prefer accessibility tree then local OCR; mask sensitive fields and denylist password managers, banking and private apps. Masking imperfect: show selected scope and refuse unsupported protected content. R3 camera snapshot only when requested, per-session consent and indicator, stop on lock/cancel. No face recognition, covert monitoring, biometric storage or continuous environmental video. Use local OCR or optional vision model; vision requires GPU lease and separate capability benchmark. Raw frames in memory only; explicit save is separate R2 action.

## 3. Web connector
Search provider is unresolved: select lawful documented API or user-approved browser search, respecting terms, quotas and potential fees. No mandatory paid provider. If no approved free provider, open user browser for manual search or return unavailable; do not scrape by default. Public queries only unless approved redacted preview. Fetch through dedicated read-only client with SSRF protections (09), no scripts, cookies or credential carryover; extract safe text, cite canonical URL, title, retrieval time and publication date if available. Cache public data short TTL 15min default, stale label offline. No automated form submission, checkout, account login, email send.

## 4. Personal connectors
Local SQLite tasks/calendar/expenses/habits first. Calendar/email optional read-only R2: OAuth authorization code with PKCE where provider supports desktop clients, system browser, minimal scopes, token stored in vault, disconnect/revoke and purge cached data. Explicit consent for data imported into local knowledge. External source IDs dedup and last_synced metadata; rate limit/429 backoff. Never overwrite external calendar or send email baseline. External services may require registration, network, fees or approval; validate provider-specific API/terms before enabling.

## 5. Home Assistant
R3 HA REST or WebSocket for state, typed service calls for allowlisted light/media/safe plugs only if verified not safety-critical. Device category allowlist plus per-entity grant; block locks, alarms, heat, medical/safety systems, unknown outlets and high-impact actuation. Token in vault; use dedicated limited account/proxy, verify effective scope because HA tokens may inherit broader user privileges. TLS/private network; no direct generic MQTT publish tool. MQTT if needed behind HA with scoped topics and broker ACL. Readback fresh state, timeout unknown, no toggle retry (use explicit desired state). Disconnect → mark unavailable; never queue unsafe commands for later. Device list/addresses TBD by owner.

## 6. Mobile and remote
R3 responsive web client hosted by separate local gateway, reachable only via private VPN with explicit device ACL and TLS. Local pairing displays short-lived challenge, user confirms device fingerprint, issue revocable scoped token; mobile stores credentials in secure storage when available; browser fallback secure HttpOnly SameSite session, CSRF defense. Initially only chat, read status and create/list reminders. No remote screen/camera, file mutation, security configuration, approval or general tool access. Rate limit, short idle expiry (15 min candidate), token rotation/revoke on device removal. Workstation must be awake, network active and local session policy allows; no remote wake baseline. Verify VPN config rather than assume defaults; no public IP/port forwarding.

## 7. Integration reliability contract
Each adapter declares capability, supported channels, risk, timeout, idempotency, error map, health probe, verification method, credentials reference and opt-in setting. Test with mocks first, then controlled live sandbox and user permission. Reads can retry bounded with jitter; write uncertain triggers readback/reconciliation, not blind retry. No adapter may call model, access DB directly, or bypass policy. Revoke immediately blocks new work and queued effects. Track compatibility matrix (OS build, app version, device firmware, connector scopes, last tested date) as implementation artifact.

## Optional private inference server (R2)
Separate provider adapter, not the remote mobile gateway. Explicitly enroll user-controlled LAN server with TLS identity, scoped credential, model capability probe and per-data consent. No arbitrary endpoint routing, public cloud or automatic local-to-LAN fallback; on disconnect mark unavailable and use only approved same-zone fallback or direct mode. Provider may retain data; owner must verify its retention configuration. See 06 §6 and 09.
