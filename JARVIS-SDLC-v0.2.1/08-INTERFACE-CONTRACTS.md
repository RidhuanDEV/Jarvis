# API, IPC, Events, Configuration & Tool Contracts

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Transport conventions & platform IPC abstraction
UI React berkomunikasi hanya melalui perintah Tauri IPC yang terdaftar eksplisit dalam `capabilities/*.json`. Broker native meneruskan permintaan ke proses Core melalui `LocalIpcTransportPort` (implementasi utama pada Windows: *Named Pipe* khusus SID pengguna aktif + token rahasia per-peluncuran `≥ 256-bit`; mode loopback `127.0.0.1` terautentikasi tanpa CORS dan dengan validasi `Host`/`Origin` tersedia bagi harness pengujian terisolasi). WebView tidak pernah menerima token rahasia Core maupun memanggil proses runtime AI secara langsung.

Payload menggunakan JSON UTF-8 berversi (`schema_version: 1`, ukuran maks `256 KiB`; referensi berkas memakai `root_id + relative_path` atau `manifest_id`, bukan jalur mentah tak tervalidasi). Kode status mengikuti semantik konsisten: `200/201` selesai sinkron, `202` diterima asinkron (*bukan* klaim selesai), `401` tak terautentikasi, `403` ditolak policy, `409` konflik revisi/idempotensi, `422` validasi gagal, `429` antrean penuh, `503` komponen terdegradasi. Setiap respons galat memuat `code`, `message` aman, `correlation_id`, dan flag `retryable`.

## 2. Katalog operasi IPC dan rute internal
| Kelompok kontrak | Operasi IPC / Rute internal (`/v1/...`) | Ringkasan muatan & hasil | Fase |
|---|---|---|---|
| Percakapan & eksekusi | `submit_turn` (`POST /v1/requests`), `get_request`, `cancel_request` | Teks/kanal, `client_request_id` → `request_id`, state, hasil langkah teredaksi | `R1` |
| Persetujuan `R2` | `approve_action` (`POST /v1/approvals/{id}/decision`) | `decision`, `nonce`, `bound_hash` dari dialog native lokal | `R1` |
| Audio & perangkat | `audio.get_state`, `audio.set_mode`, `audio.select_devices`, `audio.test` | Mode `muted/wake/ptt`, pemilihan input/output dinamis, tes voice/mic | `R1` |
| Kapabilitas & rekomendasi | `system.discover` (`GET /v1/system/capabilities`), `config.recommend` | Snapshot CPU/RAM/GPU/disk/audio/display/daya + profil rekomendasi & tier dukungan | `R1` |
| Konfigurasi & onboarding | `config.get/update/export/import/rollback`, `onboarding.complete_step` | Skema konfigurasi berversi, preferensi bahasa/timezone/persona/visual, status onboarding | `R1` |
| Manajemen storage | `storage.list_volumes`, `storage.get_locations`, `storage.set_location`, `storage.migrate` (`R2`), `storage.cleanup_cache` | 11 lokasi penyimpanan, kuota cache, pratinjau ruang bebas, status migrasi & rollback | `R1`/`R2` |
| Provider, runtime & model | `provider.list/probe/configure/revoke`, `model.list/import/verify/remove`, `profile.list/activate/rollback`, `benchmark.start/cancel` | Mode kepemilikan (`managed_local`/`external_local`/`authorized_lan`/`custom_compatible`), aktivasi atomik, benchmark berizin | `R1`/`R2` |
| Lisensi & ekstensi | `license.inventory`, `license.export_notices`, `extension.list/install/toggle` (`R2`) | Inventaris 11 kategori artefak, SBOM/`NOTICE`, paket ekstensi berversi | `R1`/`R2` |
| Memori & pengingat | `memories` (`GET/POST/PATCH/DELETE`), `reminders` (`GET/POST/PATCH/DELETE`) | CRUD dengan `expected_revision`, provenance, IANA timezone, *snooze/dismiss* | `R1` |
| Izin, backup & kesehatan | `grants` (`GET/PUT`), `backups` (`create/verify/restore`), `health` (`GET /v1/health`) | Matriks izin `R0`–`R3`, snapshot `Argon2id/AES-GCM`, kesiapan per komponen | `R1` |
| Pengetahuan, web, layar, life & workflow | `/v1/roots`, `/v1/index/jobs`, `/v1/web/query`, `/v1/screen/analyze`, `/v1/{tasks,calendar,expenses,habits}`, `/v1/workflows` | Kontrak domain produktivitas tervalidasi | `R2` |
| IoT & gateway remote | `/v1/iot/entities`, gateway terpisah `/remote/v1/{session,requests,reminders,status}` | Allowlist Home Assistant & rute sempit perangkat mobile terpasangkan | `R3` |

## 3. Kontrak skema Tool Registry & katalog status
```json
{
  "tool_id": "os.volume.set",
  "version": 1,
  "risk": "R1",
  "channels": ["local"],
  "capability": "os.volume",
  "timeout_ms": 3000,
  "idempotent": true,
  "input_schema": {
    "type": "object",
    "properties": { "percent": { "type": "integer", "minimum": 0, "maximum": 100 } },
    "required": ["percent"],
    "additionalProperties": false
  },
  "verification": "readback_volume"
}
```
Proposal dari model hanya boleh berisi `{"steps":[{"tool_id":"...","version":1,"args":{...}}]}` (`maks 5` langkah, `additionalProperties: false`). Konteks `actor`, `session`, `risk`, `grant`, `idempotency_key`, dan batas waktu disuntikkan secara eksklusif oleh sisi server. Katalog kode galat terstandar: `INVALID_ARGS`, `DENIED`, `APPROVAL_REQUIRED`, `APPROVAL_EXPIRED`, `TARGET_CHANGED`, `TARGET_AMBIGUOUS`, `NOT_FOUND`, `OFFLINE`, `INSUFFICIENT_DISK`, `UNSUPPORTED_FILESYSTEM`, `RUNTIME_UNAVAILABLE`, `WORKER_OOM`, `LICENSE_UNVERIFIED`, `TOOL_TIMEOUT`, `VERIFY_TIMEOUT`, `QUEUE_FULL`, `CANCELED`, `UNSUPPORTED`, `INTERNAL`.

## 4. Pemisahan jalur Event Sekuensial vs Telemetri Ephemeral
1. **Reliable Sequenced Domain Stream (`/v1/events` via SSE/IPC):** Membawa perubahan state otoritatif dengan amplop `{"schema_version":1,"event_id":"uuid","seq":42,"request_id":"...","correlation_id":"...","type":"request.state_changed","occurred_at":"...","payload":{...}}`. Jenis event mencakup: `voice.state_changed`, `audio.devices_changed`, `request.state_changed`, `approval.required`, `action.completed`, `job.due`, `reminder.delivered`, `provider.health_changed`, `profile.switch.started/committed/failed`, `storage.migration_progress`, `storage.space_low`, `resource.pressure_changed`, `visual.recommendation_changed`, `knowledge.index_progress`, dan `permission.revoked`. Mendukung penyambungan ulang dengan kursor `seq` dan resinkronisasi penuh bila kursor kedaluwarsa.
2. **Ephemeral Real-Time Signal Channel (Tauri `Channel` terpisah):** Mengirimkan amplitudo ternormalisasi `voice.envelope` (`0.0..1.0`, dibatasi `≤ 30 Hz`, nol PCM mentah) dan sampel ringkas metrik frame/resource saat jendela tampil di foreground, sehingga tidak membanjiri antrean kursor event domain maupun log audit.

## 5. Kompatibilitas skema & kontrak ekstensi (`DEC-017`, `DEC-024`)
Setiap skema konfigurasi, manifest model, dan paket ekstensi mencantumkan `schema_version` dan `sdk_version`. Perubahan yang merusak kompatibilitas memerlukan migrasi skema teruji dan pembaruan `RTM`. Snapshot spesifikasi OpenAPI dan definisi tipe TypeScript/JSON Schema dihasilkan otomatis dari kode sumber saat implementasi dan diverifikasi pada CI.
