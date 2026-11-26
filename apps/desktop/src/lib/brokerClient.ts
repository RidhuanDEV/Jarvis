import { invoke } from '@tauri-apps/api/core'
import {
  HardwareCapabilitiesResponseSchema,
  LicenseInventoryResponseSchema,
  StorageLocationsResponseSchema,
  type HardwareCapabilitiesResponse,
  type LicenseArtifact,
  type StorageLocation,
} from './contracts'

function isTauriRuntime(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window
}

export interface FoundationBootstrapData {
  readonly capabilities: HardwareCapabilitiesResponse
  readonly storageLocations: ReadonlyArray<StorageLocation>
  readonly licenses: ReadonlyArray<LicenseArtifact>
  readonly source: 'tauri_broker' | 'preview_fixture'
}

const PREVIEW_CAPABILITIES: HardwareCapabilitiesResponse = {
  schema_version: 1,
  snapshot: {
    id: 'preview-local-snapshot',
    os_info: { system: 'Desktop', release: 'Local', version: 'Preview', arch: 'x64' },
    cpu: { model_name: 'Dynamic Host Probe (Preview)', physical_cores: 6, logical_cores: 12 },
    ram_total_bytes: 16 * 1024 * 1024 * 1024,
    ram_available_bytes: 10 * 1024 * 1024 * 1024,
    gpus: [],
    displays: [
      {
        name: 'Primary Display',
        width_px: 1920,
        height_px: 1080,
        refresh_hz: 120,
        scale_percent: 100,
        is_primary: true,
      },
    ],
    power_state: 'ac',
    captured_at: '2026-11-26T00:00:00Z',
  },
  recommendation: {
    support_tier: 'Supported',
    hardware_class: 'cpu_only_16gb_plus',
    recommended_ai_mode: 'balanced',
    recommended_backend: 'cpu',
    recommended_runtime_ownership: 'managed_local',
    recommended_model_class: '1.7B-3B quantized (CPU int4/Q4_K_M)',
    recommended_max_ram_mib: 7372,
    recommended_max_vram_mib: 0,
    recommended_cpu_threads: 6,
    recommended_context_tokens: 4096,
    recommended_visual_tier: 'balanced',
    recommended_fps_target: 'auto',
    reasons: [
      'Pratinjau deteksi perangkat keras dinamis — tidak mengunci spesifikasi mesin tertentu.',
      'Target FPS Auto menyesuaikan refresh rate monitor aktif tanpa batas permanen 60 FPS.',
    ],
    warnings: [],
  },
}

const PREVIEW_STORAGE: ReadonlyArray<StorageLocation> = [
  { category: 'app_data', resolved_path: '<OS_APP_DATA>/Jarvis', quota_bytes: null, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
  { category: 'models', resolved_path: '<OS_APP_DATA>/Jarvis/models', quota_bytes: null, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
  { category: 'runtimes', resolved_path: '<OS_APP_DATA>/Jarvis/runtimes', quota_bytes: null, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
  { category: 'core_db', resolved_path: '<OS_APP_DATA>/Jarvis/db/core', quota_bytes: null, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
  { category: 'knowledge_db', resolved_path: '<OS_APP_DATA>/Jarvis/db/knowledge', quota_bytes: null, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
  { category: 'logs', resolved_path: '<OS_APP_DATA>/Jarvis/logs', quota_bytes: null, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
  { category: 'temp', resolved_path: '<OS_CACHE>/Jarvis/temp', quota_bytes: null, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
  { category: 'cache', resolved_path: '<OS_CACHE>/Jarvis/cache', quota_bytes: 10 * 1024 * 1024 * 1024, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
  { category: 'backups', resolved_path: '<OS_APP_DATA>/Jarvis/backups', quota_bytes: null, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
  { category: 'imported_docs', resolved_path: '<OS_APP_DATA>/Jarvis/imported_docs', quota_bytes: null, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
  { category: 'extensions', resolved_path: '<OS_APP_DATA>/Jarvis/extensions', quota_bytes: null, is_removable: false, filesystem_kind: 'NTFS', status: 'healthy', updated_at: '2026-11-26T00:00:00Z' },
]

const PREVIEW_LICENSES: ReadonlyArray<LicenseArtifact> = [
  {
    schema_version: 1,
    id: 'pkg-tauri',
    category: 'app_package',
    name: 'Tauri 2',
    version_or_rev: '2.12.5',
    license_spdx: 'Apache-2.0',
    obligations: ['attribution_notice', 'include_license_text', 'preserve_copyright'],
    source_url: 'https://github.com/tauri-apps/tauri',
    notice_text: 'Apache-2.0 / MIT.',
    verified_at: '2026-11-26T00:00:00Z',
  },
  {
    schema_version: 1,
    id: 'voice-piper-tts-gpl',
    category: 'voice_asset',
    name: 'OHF-Voice piper1-gpl (Optional Offline TTS)',
    version_or_rev: '1.8.0',
    license_spdx: 'GPL-3.0-or-later',
    obligations: [
      'attribution_notice',
      'include_license_text',
      'source_offer_or_distribution',
      'model_card_notice',
      'upstream_dataset_review',
    ],
    source_url: 'https://github.com/OHF-Voice/piper1-gpl',
    notice_text: 'GPL-3.0-or-later with espeak-ng; source offer & upstream MODEL_CARD review required.',
    verified_at: '2026-11-26T00:00:00Z',
  },
]

export async function loadFoundationData(): Promise<FoundationBootstrapData> {
  if (!isTauriRuntime()) {
    return {
      capabilities: PREVIEW_CAPABILITIES,
      storageLocations: PREVIEW_STORAGE,
      licenses: PREVIEW_LICENSES,
      source: 'preview_fixture',
    }
  }

  try {
    const [rawCaps, rawStorage, rawLicenses]: [unknown, unknown, unknown] = await Promise.all([
      invoke('discover_capabilities'),
      invoke('get_storage_locations'),
      invoke('get_license_inventory'),
    ])
    const caps = HardwareCapabilitiesResponseSchema.parse(rawCaps)
    const storage = StorageLocationsResponseSchema.parse(rawStorage)
    const licenses = LicenseInventoryResponseSchema.parse(rawLicenses)
    return {
      capabilities: caps,
      storageLocations: storage.locations,
      licenses: licenses.artifacts,
      source: 'tauri_broker',
    }
  } catch {
    return {
      capabilities: PREVIEW_CAPABILITIES,
      storageLocations: PREVIEW_STORAGE,
      licenses: PREVIEW_LICENSES,
      source: 'preview_fixture',
    }
  }
}

export async function dispatchApprovalDecision(payload: {
  readonly approvalId: string
  readonly decision: 'approve' | 'reject'
  readonly nonce: string
  readonly boundHash: string
}): Promise<boolean> {
  if (!isTauriRuntime()) {
    return true
  }
  await invoke('submit_approval_decision', {
    payload: {
      approval_id: payload.approvalId,
      decision: payload.decision,
      nonce: payload.nonce,
      bound_hash: payload.boundHash,
    },
  })
  return true
}
