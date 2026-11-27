//! Allowlisted typed Tauri IPC commands forwarding to local Core with Rust-owned auth token.

use crate::ipc_transport::LocalIpcTransport;
use crate::process_supervisor::ProcessSupervisor;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;
use std::time::Duration;
use tauri::State;

const STANDARD_REQUEST_TIMEOUT: Duration = Duration::from_secs(15);
const LONG_TURN_REQUEST_TIMEOUT: Duration = Duration::from_secs(90);

pub struct BrokerState {
    pub transport: Arc<dyn LocalIpcTransport>,
    pub supervisor: Arc<dyn ProcessSupervisor>,
    pub http: reqwest::Client,
    pub core_port: u16,
    pub core_pid: Option<u32>,
    pub core_launch_error: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct BrokerStatus {
    pub transport_ready: bool,
    pub core_connected: bool,
    pub core_port: u16,
    pub core_pid: Option<u32>,
    pub core_error: Option<String>,
    pub offline_default: bool,
    pub version: &'static str,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct ApprovalDecisionPayload {
    pub approval_id: String,
    pub decision: String,
    pub nonce: String,
    pub bound_hash: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct SetStorageLocationPayload {
    pub category: String,
    pub path: String,
    pub quota_bytes: Option<u64>,
}

async fn forward_get(state: &BrokerState, path: &str) -> Result<Value, String> {
    let url = format!("{}{}", state.transport.base_url(), path);
    let resp = state
        .http
        .get(&url)
        .timeout(STANDARD_REQUEST_TIMEOUT)
        .header("Authorization", state.transport.bearer_header_value())
        .send()
        .await
        .map_err(|e| format!("Core IPC unreachable: {e}"))?;
    let status = resp.status();
    let body: Value = resp
        .json()
        .await
        .map_err(|e| format!("Invalid JSON from Core ({status}): {e}"))?;
    if !status.is_success() {
        return Err(body.to_string());
    }
    Ok(body)
}

async fn forward_json_with_timeout(
    state: &BrokerState,
    method: reqwest::Method,
    path: &str,
    payload: &Value,
    timeout: Duration,
) -> Result<Value, String> {
    let url = format!("{}{}", state.transport.base_url(), path);
    let resp = state
        .http
        .request(method, &url)
        .timeout(timeout)
        .header("Authorization", state.transport.bearer_header_value())
        .json(payload)
        .send()
        .await
        .map_err(|e| format!("Core IPC unreachable: {e}"))?;
    let status = resp.status();
    let body: Value = resp
        .json()
        .await
        .map_err(|e| format!("Invalid JSON from Core ({status}): {e}"))?;
    if !status.is_success() {
        return Err(body.to_string());
    }
    Ok(body)
}

async fn forward_json(
    state: &BrokerState,
    method: reqwest::Method,
    path: &str,
    payload: &Value,
) -> Result<Value, String> {
    forward_json_with_timeout(state, method, path, payload, STANDARD_REQUEST_TIMEOUT).await
}

/// Validate an opaque URL path segment before forwarding to Core (IR-08 / DEF-21).
/// Rejects path traversal (`..`), slashes, percent-encoding, query/fragment delimiters, and whitespace.
fn validate_path_segment<'a>(raw: &'a str, field_name: &str) -> Result<&'a str, String> {
    if raw.is_empty() || raw.len() > 128 {
        return Err(format!("Invalid {field_name}: must be 1..=128 characters."));
    }
    if raw.contains("..") {
        return Err(format!("Invalid {field_name}: path traversal sequence rejected."));
    }
    if !raw
        .bytes()
        .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_' | b'.'))
    {
        return Err(format!(
            "Invalid {field_name}: only ASCII alphanumeric, '-', '_', and '.' are allowed."
        ));
    }
    Ok(raw)
}

#[tauri::command]
pub async fn get_broker_status(state: State<'_, BrokerState>) -> Result<BrokerStatus, String> {
    let health_url = format!("{}/healthz", state.transport.base_url());
    let connected = match state.http.get(&health_url).send().await {
        Ok(resp) => resp.status().is_success(),
        Err(_) => false,
    };
    Ok(BrokerStatus {
        transport_ready: true,
        core_connected: connected,
        core_port: state.core_port,
        core_pid: state.core_pid,
        core_error: if connected {
            None
        } else {
            state.core_launch_error.clone()
        },
        offline_default: true,
        version: "0.2.1",
    })
}

#[tauri::command]
pub async fn discover_capabilities(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/system/capabilities").await
}

#[tauri::command]
pub async fn get_config(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/config").await
}

#[tauri::command]
pub async fn get_storage_locations(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/storage/locations").await
}

#[tauri::command]
pub async fn set_storage_location(
    state: State<'_, BrokerState>,
    payload: SetStorageLocationPayload,
) -> Result<Value, String> {
    let category = validate_path_segment(&payload.category, "category")?;
    let path = format!("/v1/storage/locations/{category}");
    let body = serde_json::json!({
        "path": payload.path,
        "quota_bytes": payload.quota_bytes,
    });
    forward_json(&state, reqwest::Method::PUT, &path, &body).await
}

#[tauri::command]
pub async fn get_license_inventory(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/licenses/inventory").await
}

#[tauri::command]
pub async fn submit_approval_decision(
    state: State<'_, BrokerState>,
    payload: ApprovalDecisionPayload,
) -> Result<Value, String> {
    let approval_id = validate_path_segment(&payload.approval_id, "approval_id")?;
    let path = format!("/v1/approvals/{approval_id}/decision");
    let body = serde_json::json!({
        "decision": payload.decision,
        "nonce": payload.nonce,
        "bound_hash": payload.bound_hash,
        "modality": "trusted_ui",
        "channel": "local"
    });
    forward_json(&state, reqwest::Method::POST, &path, &body).await
}

#[tauri::command]
pub async fn lock_session(state: State<'_, BrokerState>, reason: String) -> Result<Value, String> {
    let body = serde_json::json!({ "reason": reason });
    forward_json(&state, reqwest::Method::POST, "/v1/session/lock", &body).await
}

#[tauri::command]
pub async fn submit_turn(
    state: State<'_, BrokerState>,
    utterance: String,
    session_id: String,
) -> Result<Value, String> {
    let body = serde_json::json!({
        "utterance": utterance,
        "session_id": session_id,
        "actor_ref": "local_owner",
        "channel": "local",
        "modality": "trusted_ui"
    });
    // B07 / DEF-08: LLM turns allow up to 90s instead of aborting at global 10s timeout
    forward_json_with_timeout(
        &state,
        reqwest::Method::POST,
        "/v1/requests",
        &body,
        LONG_TURN_REQUEST_TIMEOUT,
    )
    .await
}

#[tauri::command]
pub async fn cancel_active_request(
    state: State<'_, BrokerState>,
    request_id: Option<String>,
) -> Result<Value, String> {
    // B07: cancel in-flight turn/speech cleanly WITHOUT killing Python Core or destroying Job Object
    let _ = forward_json(
        &state,
        reqwest::Method::POST,
        "/v1/voice/stop-speaking",
        &serde_json::json!({}),
    )
    .await;
    forward_json(
        &state,
        reqwest::Method::POST,
        "/v1/requests/cancel",
        &serde_json::json!({ "request_id": request_id }),
    )
    .await
}

#[tauri::command]
pub async fn poll_events_since(
    state: State<'_, BrokerState>,
    after_seq: u64,
) -> Result<Vec<Value>, String> {
    let url = format!(
        "{}/v1/events?after_seq={after_seq}&once=true",
        state.transport.base_url()
    );
    let resp = state
        .http
        .get(&url)
        .timeout(STANDARD_REQUEST_TIMEOUT)
        .header("Authorization", state.transport.bearer_header_value())
        .send()
        .await
        .map_err(|e| format!("Core SSE unreachable: {e}"))?;
    let status = resp.status();
    let text = resp
        .text()
        .await
        .map_err(|e| format!("Invalid SSE text from Core ({status}): {e}"))?;
    if !status.is_success() {
        return Err(text);
    }
    let mut events = Vec::new();
    for line in text.lines() {
        if let Some(json_str) = line.strip_prefix("data: ") {
            if let Ok(parsed) = serde_json::from_str::<Value>(json_str) {
                if parsed.get("seq").is_some() {
                    events.push(parsed);
                }
            }
        }
    }
    Ok(events)
}

#[tauri::command]
pub async fn list_installed_apps(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/apps").await
}

#[tauri::command]
pub async fn search_indexed_files(
    state: State<'_, BrokerState>,
    query: String,
    ext: Option<String>,
) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::POST,
        "/v1/files/search",
        &serde_json::json!({ "query": query, "ext": ext }),
    )
    .await
}

#[tauri::command]
pub fn get_core_stderr_logs(state: State<'_, BrokerState>) -> Vec<String> {
    state.supervisor.recent_stderr_lines()
}

#[tauri::command]
pub async fn complete_onboarding_step(
    state: State<'_, BrokerState>,
    step: u8,
    mark_completed: bool,
) -> Result<Value, String> {
    if !(1..=10).contains(&step) {
        return Err(format!("Invalid onboarding step {step}: must be 1..=10."));
    }
    let path = format!("/v1/onboarding/steps/{step}?mark_completed={mark_completed}");
    forward_json(&state, reqwest::Method::POST, &path, &serde_json::json!({})).await
}

#[tauri::command]
pub async fn upsert_grant(
    state: State<'_, BrokerState>,
    capability: String,
) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::PUT,
        "/v1/grants",
        &serde_json::json!({
            "subject_type": "local_owner",
            "subject_id": "local_owner",
            "capability": capability,
            "scope": {}
        }),
    )
    .await
}

#[tauri::command]
pub async fn get_audio_state(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/audio/state").await
}

#[tauri::command]
pub async fn set_audio_mode(state: State<'_, BrokerState>, mode: String) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::PUT,
        "/v1/audio/mode",
        &serde_json::json!({ "mode": mode }),
    )
    .await
}

#[tauri::command]
pub async fn get_live_voice_status(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/voice/live-status").await
}

#[tauri::command]
pub async fn arm_live_voice(state: State<'_, BrokerState>, mode: String) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::POST,
        "/v1/voice/arm",
        &serde_json::json!({ "mode": mode }),
    )
    .await
}

#[tauri::command]
pub async fn stop_live_speaking(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::POST,
        "/v1/voice/stop-speaking",
        &serde_json::json!({}),
    )
    .await
}

#[tauri::command]
pub async fn get_voice_diagnostics(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/voice/diagnostics").await
}

#[tauri::command]
pub async fn select_audio_devices(
    state: State<'_, BrokerState>,
    input_device_id: Option<String>,
    output_device_id: Option<String>,
) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::PUT,
        "/v1/audio/devices",
        &serde_json::json!({
            "input_device_id": input_device_id,
            "output_device_id": output_device_id
        }),
    )
    .await
}

#[tauri::command]
pub async fn set_speech_rate(
    state: State<'_, BrokerState>,
    speech_rate: f64,
) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::PUT,
        "/v1/audio/speech-rate",
        &serde_json::json!({ "speech_rate": speech_rate }),
    )
    .await
}

#[tauri::command]
pub async fn replay_voice_transcript(
    state: State<'_, BrokerState>,
    transcript: String,
    session_id: String,
    speak_reply: bool,
) -> Result<Value, String> {
    forward_json_with_timeout(
        &state,
        reqwest::Method::POST,
        "/v1/voice/replay-transcript",
        &serde_json::json!({
            "transcript": transcript,
            "session_id": session_id,
            "speak_reply": speak_reply
        }),
        LONG_TURN_REQUEST_TIMEOUT,
    )
    .await
}

#[tauri::command]
pub async fn list_memories(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/memories?include_proposals=true").await
}

#[tauri::command]
pub async fn create_memory(
    state: State<'_, BrokerState>,
    kind: String,
    content: String,
    sensitivity: String,
) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::POST,
        "/v1/memories",
        &serde_json::json!({ "kind": kind, "content": content, "sensitivity": sensitivity }),
    )
    .await
}

#[tauri::command]
pub async fn delete_memory(
    state: State<'_, BrokerState>,
    memory_id: String,
) -> Result<Value, String> {
    let safe_id = validate_path_segment(&memory_id, "memory_id")?;
    let path = format!("/v1/memories/{safe_id}");
    forward_json(&state, reqwest::Method::DELETE, &path, &serde_json::json!({})).await
}

#[tauri::command]
pub async fn list_reminders(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/reminders").await
}

#[tauri::command]
pub async fn create_reminder(
    state: State<'_, BrokerState>,
    title: String,
    due_at_utc: String,
    timezone_iana: String,
) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::POST,
        "/v1/reminders",
        &serde_json::json!({
            "title": title,
            "due_at_utc": due_at_utc,
            "timezone_iana": timezone_iana
        }),
    )
    .await
}

#[tauri::command]
pub async fn list_profiles(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/profiles").await
}

#[tauri::command]
pub async fn activate_profile(
    state: State<'_, BrokerState>,
    profile_id: String,
) -> Result<Value, String> {
    let safe_id = validate_path_segment(&profile_id, "profile_id")?;
    let path = format!("/v1/profiles/{safe_id}/activate");
    forward_json(&state, reqwest::Method::POST, &path, &serde_json::json!({})).await
}

#[tauri::command]
pub async fn rollback_profile(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_json(&state, reqwest::Method::POST, "/v1/profiles/rollback", &serde_json::json!({}))
        .await
}

#[tauri::command]
pub async fn list_knowledge_roots(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/roots").await
}

#[tauri::command]
pub async fn query_knowledge(state: State<'_, BrokerState>, query: String) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::POST,
        "/v1/knowledge/query",
        &serde_json::json!({ "query": query }),
    )
    .await
}

#[tauri::command]
pub async fn list_tasks(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/tasks").await
}

#[tauri::command]
pub async fn get_expense_summary(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/expenses/summary").await
}

#[tauri::command]
pub async fn list_workflows(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/workflows").await
}

#[tauri::command]
pub async fn list_extensions(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/extensions").await
}

#[tauri::command]
pub async fn list_ha_entities(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/iot/ha/entities").await
}

#[tauri::command]
pub async fn list_remote_devices(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/remote/devices").await
}

#[tauri::command]
pub async fn revoke_remote_device(
    state: State<'_, BrokerState>,
    device_id: String,
) -> Result<Value, String> {
    let safe_id = validate_path_segment(&device_id, "device_id")?;
    let path = format!("/v1/remote/devices/{safe_id}");
    forward_json(&state, reqwest::Method::DELETE, &path, &serde_json::json!({})).await
}

#[tauri::command]
pub async fn list_preference_proposals(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_get(&state, "/v1/preferences/proposals").await
}

#[tauri::command]
pub async fn add_knowledge_root(state: State<'_, BrokerState>, path: String) -> Result<Value, String> {
    forward_json(&state, reqwest::Method::POST, "/v1/roots", &serde_json::json!({ "path": path })).await
}

#[tauri::command]
pub async fn revoke_knowledge_root(state: State<'_, BrokerState>, root_id: String) -> Result<Value, String> {
    let safe_id = validate_path_segment(&root_id, "root_id")?;
    let path = format!("/v1/roots/{safe_id}");
    forward_json(&state, reqwest::Method::DELETE, &path, &serde_json::json!({})).await
}

#[tauri::command]
pub async fn create_task(state: State<'_, BrokerState>, title: String) -> Result<Value, String> {
    forward_json(&state, reqwest::Method::POST, "/v1/tasks", &serde_json::json!({ "title": title })).await
}

#[tauri::command]
pub async fn record_expense(
    state: State<'_, BrokerState>,
    amount_minor: i64,
    currency_iso: String,
    kind: String,
    category: String,
) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::POST,
        "/v1/expenses",
        &serde_json::json!({
            "amount_minor": amount_minor,
            "currency_iso": currency_iso,
            "kind": kind,
            "category": category
        }),
    )
    .await
}

#[tauri::command]
pub async fn add_ha_entity(
    state: State<'_, BrokerState>,
    entity_id: String,
    friendly_name: String,
) -> Result<Value, String> {
    forward_json(
        &state,
        reqwest::Method::POST,
        "/v1/iot/ha/entities",
        &serde_json::json!({
            "entity_id": entity_id,
            "friendly_name": friendly_name,
            "allowed_actions": ["read_state", "turn_on", "turn_off"]
        }),
    )
    .await
}

#[tauri::command]
pub async fn decide_preference_proposal(
    state: State<'_, BrokerState>,
    proposal_id: String,
    decision: String,
) -> Result<Value, String> {
    let safe_id = validate_path_segment(&proposal_id, "proposal_id")?;
    let path = format!("/v1/preferences/proposals/{safe_id}/decide");
    forward_json(
        &state,
        reqwest::Method::POST,
        &path,
        &serde_json::json!({ "decision": decision }),
    )
    .await
}

#[tauri::command]
pub fn emergency_stop_managed_workers(state: State<'_, BrokerState>) -> usize {
    state.supervisor.close_all_managed()
}

#[cfg(test)]
mod tests {
    use super::validate_path_segment;

    #[test]
    fn accepts_valid_opaque_identifiers() {
        assert!(validate_path_segment("core_db", "category").is_ok());
        assert!(validate_path_segment("550e8400-e29b-41d4-a716-446655440000", "approval_id").is_ok());
        assert!(validate_path_segment("balanced.v2", "profile_id").is_ok());
    }

    #[test]
    fn rejects_path_traversal_and_url_injection() {
        for bad in [
            "",
            "../grants",
            "..\\grants",
            "id/extra",
            "id%2fextra",
            "id?admin=true",
            "id#frag",
            "has space",
        ] {
            assert!(
                validate_path_segment(bad, "test_id").is_err(),
                "expected rejection for malicious segment: {bad:?}"
            );
        }
    }
}
