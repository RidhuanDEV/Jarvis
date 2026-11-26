//! Allowlisted typed Tauri IPC commands forwarding to local Core with Rust-owned auth token.

use crate::ipc_transport::LocalIpcTransport;
use crate::process_supervisor::ProcessSupervisor;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Arc;
use tauri::State;

pub struct BrokerState {
    pub transport: Arc<dyn LocalIpcTransport>,
    pub supervisor: Arc<dyn ProcessSupervisor>,
    pub http: reqwest::Client,
}

#[derive(Debug, Serialize)]
pub struct BrokerStatus {
    pub transport_ready: bool,
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

async fn forward_json(
    state: &BrokerState,
    method: reqwest::Method,
    path: &str,
    payload: &Value,
) -> Result<Value, String> {
    let url = format!("{}{}", state.transport.base_url(), path);
    let resp = state
        .http
        .request(method, &url)
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

#[tauri::command]
pub fn get_broker_status() -> BrokerStatus {
    BrokerStatus {
        transport_ready: true,
        offline_default: true,
        version: "0.2.1",
    }
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
    let path = format!("/v1/storage/locations/{}", payload.category);
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
    let path = format!("/v1/approvals/{}/decision", payload.approval_id);
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
    forward_json(&state, reqwest::Method::POST, "/v1/requests", &body).await
}

#[tauri::command]
pub async fn complete_onboarding_step(
    state: State<'_, BrokerState>,
    step: u8,
    mark_completed: bool,
) -> Result<Value, String> {
    let path = format!("/v1/onboarding/steps/{step}?mark_completed={mark_completed}");
    forward_json(&state, reqwest::Method::POST, &path, &serde_json::json!({})).await
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
    let path = format!("/v1/memories/{memory_id}");
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
    let path = format!("/v1/profiles/{profile_id}/activate");
    forward_json(&state, reqwest::Method::POST, &path, &serde_json::json!({})).await
}

#[tauri::command]
pub async fn rollback_profile(state: State<'_, BrokerState>) -> Result<Value, String> {
    forward_json(&state, reqwest::Method::POST, "/v1/profiles/rollback", &serde_json::json!({}))
        .await
}

#[tauri::command]
pub fn emergency_stop_managed_workers(state: State<'_, BrokerState>) -> usize {
    state.supervisor.close_all_managed()
}
