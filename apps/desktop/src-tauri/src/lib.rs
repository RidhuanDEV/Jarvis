//! J.A.R.V.I.S. Native Desktop Broker Library (Tauri 2 + System Tray + IPC + Process Supervisor).

pub mod commands;
pub mod core_launcher;
pub mod ipc_transport;
pub mod process_supervisor;
pub mod single_instance;

use crate::commands::BrokerState;
use crate::core_launcher::{pick_ephemeral_loopback_port, spawn_local_core};
use crate::ipc_transport::{AuthenticatedLocalTransport, LocalIpcTransport};
use crate::process_supervisor::{NativeProcessSupervisor, ProcessSupervisor};
use crate::single_instance::SingleInstanceGuard;
use std::sync::Arc;
use std::time::Duration;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Emitter, Manager};

const SINGLE_INSTANCE_MUTEX: &str = "Local\\JARVIS_PERSONAL_INTELLIGENCE_OS_V1";
const MAIN_WINDOW_TITLE: &str = "J.A.R.V.I.S. — Personal Intelligence OS";

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Prevent WebView2 HRESULT 0x800700AA lock collisions when clicking app twice:
    // if already running, bring the active window to front and exit cleanly.
    let _single_instance = match SingleInstanceGuard::acquire(SINGLE_INSTANCE_MUTEX, MAIN_WINDOW_TITLE) {
        Some(guard) => guard,
        None => return,
    };

    let port = pick_ephemeral_loopback_port().unwrap_or(47123);
    let token = AuthenticatedLocalTransport::generate_random_token();
    let transport = Arc::new(
        AuthenticatedLocalTransport::new_loopback(port, token.clone())
            .expect("valid CSPRNG 256-bit IPC token"),
    );
    let supervisor = Arc::new(
        NativeProcessSupervisor::new().expect("initialize platform process supervisor"),
    );

    // Spawn local Python Core under Win32 Job Object (KILL_ON_JOB_CLOSE) with token piped via stdin
    let launch = spawn_local_core(supervisor.as_ref(), port, &token);

    // B07 / DEF-08: use connect_timeout only; per-operation timeouts (15s CRUD / 90s LLM turn) applied per command
    let http = reqwest::Client::builder()
        .connect_timeout(Duration::from_secs(5))
        .no_proxy()
        .build()
        .expect("build loopback reqwest client");

    let sse_transport = transport.clone();
    let sse_http = http.clone();

    let state = BrokerState {
        transport,
        supervisor: supervisor.clone(),
        http,
        core_port: port,
        core_pid: launch.process.as_ref().map(|p| p.pid),
        core_launch_error: launch.error,
    };

    tauri::Builder::default()
        .manage(state)
        .setup(|app| {
            // BR-22: System Tray provides <= 2 interaction access to Stop, Mute, Offline, Show & Quit
            let show_item = MenuItem::with_id(app, "show", "Open Command Center", true, None::<&str>)?;
            let stop_item = MenuItem::with_id(app, "stop_all", "Stop Active Action", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit J.A.R.V.I.S.", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &stop_item, &quit_item])?;

            let mut tray_builder = TrayIconBuilder::new()
                .tooltip(MAIN_WINDOW_TITLE)
                .menu(&menu)
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app_handle = tray.app_handle();
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .on_menu_event(|app_handle, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let _ = window.unminimize();
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "stop_all" => {
                        // B07 / DEF-08: cancel active turn & speech cleanly WITHOUT killing Python Core!
                        let broker = app_handle.state::<BrokerState>();
                        let base_url = broker.transport.base_url().to_string();
                        let auth = broker.transport.bearer_header_value();
                        let client = broker.http.clone();
                        tauri::async_runtime::spawn(async move {
                            let _ = client
                                .post(format!("{base_url}/v1/voice/stop-speaking"))
                                .timeout(Duration::from_secs(5))
                                .header("Authorization", &auth)
                                .json(&serde_json::json!({}))
                                .send()
                                .await;
                            let _ = client
                                .post(format!("{base_url}/v1/requests/cancel"))
                                .timeout(Duration::from_secs(5))
                                .header("Authorization", &auth)
                                .json(&serde_json::json!({}))
                                .send()
                                .await;
                        });
                    }
                    "quit" => {
                        let broker = app_handle.state::<BrokerState>();
                        let _ = broker.supervisor.close_all_managed();
                        app_handle.exit(0);
                    }
                    _ => {}
                });

            if let Some(icon) = app.default_window_icon().cloned() {
                tray_builder = tray_builder.icon(icon);
            }
            let _tray = tray_builder.build(app)?;

            // B08: Background authenticated SSE cursor bridge forwarding Core domain events to WebView
            let app_handle_sse = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let mut cursor: u64 = 0;
                let mut backoff_ms: u64 = 400;
                loop {
                    let url = format!(
                        "{}/v1/events?after_seq={cursor}&once=true",
                        sse_transport.base_url()
                    );
                    let req = sse_http
                        .get(&url)
                        .timeout(Duration::from_secs(10))
                        .header("Authorization", sse_transport.bearer_header_value())
                        .send()
                        .await;
                    match req {
                        Ok(resp) if resp.status().is_success() => {
                            backoff_ms = 400;
                            if let Ok(text) = resp.text().await {
                                for line in text.lines() {
                                    if let Some(json_str) = line.strip_prefix("data: ") {
                                        if let Ok(val) = serde_json::from_str::<serde_json::Value>(json_str) {
                                            if let Some(seq) = val.get("seq").and_then(|s| s.as_u64()) {
                                                if seq > cursor {
                                                    cursor = seq;
                                                }
                                                let _ = app_handle_sse.emit("jarvis:event", val);
                                            }
                                        }
                                    }
                                }
                            }
                            tokio::time::sleep(Duration::from_millis(450)).await;
                        }
                        _ => {
                            tokio::time::sleep(Duration::from_millis(backoff_ms)).await;
                            backoff_ms = (backoff_ms * 2).min(4000);
                        }
                    }
                }
            });

            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::get_broker_status,
            commands::discover_capabilities,
            commands::get_config,
            commands::get_storage_locations,
            commands::set_storage_location,
            commands::get_license_inventory,
            commands::submit_approval_decision,
            commands::lock_session,
            commands::submit_turn,
            commands::cancel_active_request,
            commands::poll_events_since,
            commands::list_installed_apps,
            commands::search_indexed_files,
            commands::get_core_stderr_logs,
            commands::complete_onboarding_step,
            commands::upsert_grant,
            commands::get_audio_state,
            commands::set_audio_mode,
            commands::get_live_voice_status,
            commands::arm_live_voice,
            commands::stop_live_speaking,
            commands::get_voice_diagnostics,
            commands::select_audio_devices,
            commands::set_speech_rate,
            commands::replay_voice_transcript,
            commands::list_memories,
            commands::create_memory,
            commands::delete_memory,
            commands::list_reminders,
            commands::create_reminder,
            commands::list_profiles,
            commands::activate_profile,
            commands::rollback_profile,
            commands::list_knowledge_roots,
            commands::query_knowledge,
            commands::list_tasks,
            commands::get_expense_summary,
            commands::list_workflows,
            commands::list_extensions,
            commands::list_ha_entities,
            commands::list_remote_devices,
            commands::revoke_remote_device,
            commands::list_preference_proposals,
            commands::add_knowledge_root,
            commands::revoke_knowledge_root,
            commands::create_task,
            commands::record_expense,
            commands::add_ha_entity,
            commands::decide_preference_proposal,
            commands::emergency_stop_managed_workers,
        ])
        .on_window_event(move |window, event| match event {
            // B07 / DEF-08: clicking window X minimizes/hides cleanly to system tray; only Tray Quit exits app
            tauri::WindowEvent::CloseRequested { api, .. } => {
                api.prevent_close();
                let _ = window.hide();
            }
            tauri::WindowEvent::Destroyed => {
                let _ = supervisor.close_all_managed();
            }
            _ => {}
        })
        .run(tauri::generate_context!())
        .expect("error while running J.A.R.V.I.S. desktop broker");
}
