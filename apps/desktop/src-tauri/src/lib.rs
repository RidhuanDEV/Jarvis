//! J.A.R.V.I.S. Native Desktop Broker Library (Tauri 2 + System Tray + IPC + Process Supervisor).

pub mod commands;
pub mod ipc_transport;
pub mod process_supervisor;

use crate::commands::BrokerState;
use crate::ipc_transport::AuthenticatedLocalTransport;
use crate::process_supervisor::{NativeProcessSupervisor, ProcessSupervisor};
use std::sync::Arc;
use std::time::Duration;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let token = AuthenticatedLocalTransport::generate_random_token();
    let transport = Arc::new(
        AuthenticatedLocalTransport::new_loopback(47123, token)
            .expect("valid CSPRNG 256-bit IPC token"),
    );
    let supervisor = Arc::new(
        NativeProcessSupervisor::new().expect("initialize platform process supervisor"),
    );
    let http = reqwest::Client::builder()
        .timeout(Duration::from_secs(10))
        .no_proxy()
        .build()
        .expect("build loopback reqwest client");

    let state = BrokerState {
        transport,
        supervisor: supervisor.clone(),
        http,
    };

    tauri::Builder::default()
        .manage(state)
        .setup(|app| {
            // BR-22: System Tray provides <= 2 interaction access to Stop, Mute, Offline, Show & Quit
            let show_item = MenuItem::with_id(app, "show", "Open Command Center", true, None::<&str>)?;
            let stop_item = MenuItem::with_id(app, "stop_all", "Stop Active Action", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit J.A.R.V.I.S.", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &stop_item, &quit_item])?;

            let _tray = TrayIconBuilder::new()
                .menu(&menu)
                .on_menu_event(|app_handle, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app_handle.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "stop_all" => {
                        let broker = app_handle.state::<BrokerState>();
                        let _ = broker.supervisor.close_all_managed();
                    }
                    "quit" => {
                        let broker = app_handle.state::<BrokerState>();
                        let _ = broker.supervisor.close_all_managed();
                        app_handle.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;
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
            commands::complete_onboarding_step,
            commands::get_audio_state,
            commands::set_audio_mode,
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
            commands::emergency_stop_managed_workers,
        ])
        .on_window_event(move |_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                let _ = supervisor.close_all_managed();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running J.A.R.V.I.S. desktop broker");
}
