import { z } from 'zod'

export const MachineStateSchema = z.enum([
  'Startup',
  'Idle',
  'Listening',
  'Transcribing',
  'Thinking',
  'Executing',
  'Approval',
  'Speaking',
  'Success',
  'Error',
  'Muted',
  'Offline',
])
export type MachineState = z.infer<typeof MachineStateSchema>

export const VisualQualityTierSchema = z.enum([
  'cinematic',
  'balanced',
  'lite',
  'reduced_motion',
])
export type VisualQualityTier = z.infer<typeof VisualQualityTierSchema>

export const FpsTargetSchema = z.enum(['auto', '30', '60', '120', 'native'])
export type FpsTarget = z.infer<typeof FpsTargetSchema>

export const SupportTierSchema = z.enum([
  'Supported',
  'Experimental',
  'Unverified',
  'Unsupported',
])
export type SupportTier = z.infer<typeof SupportTierSchema>

export const RuntimeOwnershipModeSchema = z.enum([
  'none',
  'managed_local',
  'external_local',
  'authorized_lan',
  'custom_compatible',
])
export type RuntimeOwnershipMode = z.infer<typeof RuntimeOwnershipModeSchema>

export const StorageCategorySchema = z.enum([
  'app_data',
  'models',
  'runtimes',
  'core_db',
  'knowledge_db',
  'logs',
  'temp',
  'cache',
  'backups',
  'imported_docs',
  'extensions',
])
export type StorageCategory = z.infer<typeof StorageCategorySchema>

export const GpuInfoSchema = z.object({
  index: z.number().int().nonnegative(),
  vendor: z.enum(['nvidia', 'amd', 'intel', 'apple', 'unknown']),
  name: z.string(),
  vram_total_mib: z.number().int().nonnegative(),
  vram_free_mib: z.number().int().nonnegative(),
  driver_version: z.string(),
  is_integrated: z.boolean(),
  supports_cuda: z.boolean(),
  supports_vulkan: z.boolean(),
  supports_rocm: z.boolean(),
})

export const DisplayInfoSchema = z.object({
  name: z.string(),
  width_px: z.number().int().positive(),
  height_px: z.number().int().positive(),
  refresh_hz: z.number().positive(),
  scale_percent: z.number().int().positive(),
  is_primary: z.boolean(),
})

export const HardwareCapabilitiesResponseSchema = z.object({
  schema_version: z.literal(1),
  snapshot: z.object({
    id: z.string(),
    os_info: z.object({
      system: z.string(),
      release: z.string(),
      version: z.string(),
      arch: z.string(),
    }),
    cpu: z.object({
      model_name: z.string(),
      physical_cores: z.number().int().positive(),
      logical_cores: z.number().int().positive(),
    }),
    ram_total_bytes: z.number().int().positive(),
    ram_available_bytes: z.number().int().nonnegative(),
    gpus: z.array(GpuInfoSchema),
    displays: z.array(DisplayInfoSchema),
    power_state: z.enum(['ac', 'battery', 'battery_saver', 'unknown']),
    captured_at: z.string(),
  }),
  recommendation: z.object({
    support_tier: SupportTierSchema,
    hardware_class: z.string(),
    recommended_ai_mode: z.string(),
    recommended_backend: z.string(),
    recommended_runtime_ownership: RuntimeOwnershipModeSchema,
    recommended_model_class: z.string(),
    recommended_max_ram_mib: z.number().int().nonnegative(),
    recommended_max_vram_mib: z.number().int().nonnegative(),
    recommended_cpu_threads: z.number().int().positive(),
    recommended_context_tokens: z.number().int().positive(),
    recommended_visual_tier: VisualQualityTierSchema,
    recommended_fps_target: FpsTargetSchema,
    reasons: z.array(z.string()),
    warnings: z.array(z.string()),
  }),
})
export type HardwareCapabilitiesResponse = z.infer<typeof HardwareCapabilitiesResponseSchema>

export const StorageLocationSchema = z.object({
  category: StorageCategorySchema,
  resolved_path: z.string(),
  quota_bytes: z.number().int().nonnegative().nullable(),
  is_removable: z.boolean(),
  filesystem_kind: z.string(),
  status: z.enum(['healthy', 'degraded', 'migrating', 'offline', 'blocked']),
  updated_at: z.string(),
})
export type StorageLocation = z.infer<typeof StorageLocationSchema>

export const StorageLocationsResponseSchema = z.object({
  schema_version: z.literal(1),
  locations: z.array(StorageLocationSchema),
})

export const LicenseArtifactSchema = z.object({
  schema_version: z.literal(1),
  id: z.string(),
  category: z.string(),
  name: z.string(),
  version_or_rev: z.string(),
  license_spdx: z.string(),
  obligations: z.array(z.string()),
  source_url: z.string(),
  notice_text: z.string(),
  verified_at: z.string(),
})
export type LicenseArtifact = z.infer<typeof LicenseArtifactSchema>

export const LicenseInventoryResponseSchema = z.object({
  schema_version: z.literal(1),
  count: z.number().int().nonnegative(),
  artifacts: z.array(LicenseArtifactSchema),
})

export const ApprovalChallengeSchema = z.object({
  approval_id: z.string(),
  action_run_id: z.string(),
  tool_id: z.string(),
  tool_version: z.number().int().positive(),
  bound_hash: z.string().min(64),
  nonce: z.string().min(16),
  expires_at: z.string(),
  summary: z.string(),
  before_preview: z.string().optional(),
  after_preview: z.string().optional(),
})
export type ApprovalChallenge = z.infer<typeof ApprovalChallengeSchema>

export const SequencedDomainEventSchema = z.object({
  schema_version: z.literal(1),
  event_id: z.string(),
  seq: z.number().int().positive(),
  request_id: z.string().nullable(),
  correlation_id: z.string(),
  type: z.string(),
  occurred_at: z.string(),
  payload: z.record(z.string(), z.unknown()),
})
export type SequencedDomainEvent = z.infer<typeof SequencedDomainEventSchema>

export const MemoryItemSchema = z.object({
  id: z.string(),
  kind: z.enum(['fact', 'preference', 'instruction', 'note']),
  content: z.string(),
  is_encrypted: z.boolean(),
  sensitivity: z.enum(['normal', 'sensitive']),
  source_ref: z.string(),
  status: z.enum(['active', 'proposal', 'superseded']),
  revision: z.number().int().positive(),
  created_at: z.string(),
  updated_at: z.string(),
})
export type MemoryItem = z.infer<typeof MemoryItemSchema>

export const ReminderItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  due_at_utc: z.string(),
  timezone_iana: z.string(),
  state: z.enum(['scheduled', 'snoozed', 'delivered', 'dismissed', 'missed']),
  revision: z.number().int().positive(),
})
export type ReminderItem = z.infer<typeof ReminderItemSchema>

export const TurnResponseSchema = z.object({
  schema_version: z.literal(1),
  request_id: z.string(),
  state: z.string(),
  route_kind: z.string(),
  reply: z.string(),
  llm_called: z.boolean(),
  approval: ApprovalChallengeSchema.nullable().optional(),
})
export type TurnResponse = z.infer<typeof TurnResponseSchema>

export const KnowledgeRootItemSchema = z.object({
  id: z.string(),
  canonical_path: z.string(),
  enabled: z.boolean(),
  revision: z.number().int().positive(),
})
export type KnowledgeRootItem = z.infer<typeof KnowledgeRootItemSchema>

export const TaskItemSchema = z.object({
  id: z.string(),
  title: z.string(),
  status: z.enum(['open', 'in_progress', 'completed', 'canceled']),
  revision: z.number().int().positive(),
})
export type TaskItem = z.infer<typeof TaskItemSchema>

export const CurrencyExpenseSummarySchema = z.object({
  currency_iso: z.string(),
  total_expense_minor: z.number().int().nonnegative(),
  total_refund_minor: z.number().int().nonnegative(),
  net_spend_minor: z.number().int(),
  transaction_count: z.number().int().nonnegative(),
})
export type CurrencyExpenseSummary = z.infer<typeof CurrencyExpenseSummarySchema>

export const WorkflowItemSchema = z.object({
  id: z.string(),
  name: z.string(),
  step_count: z.number().int().min(1).max(5),
  revision: z.number().int().positive(),
  bound_hash: z.string(),
})
export type WorkflowItem = z.infer<typeof WorkflowItemSchema>

export const HaEntityItemSchema = z.object({
  entity_id: z.string(),
  domain: z.string(),
  friendly_name: z.string(),
  allowed_actions: z.array(z.string()),
  enabled: z.boolean(),
})
export type HaEntityItem = z.infer<typeof HaEntityItemSchema>

export const RemoteDeviceItemSchema = z.object({
  id: z.string(),
  label: z.string(),
  scopes: z.array(z.string()),
  revoked_at: z.string().nullable(),
})
export type RemoteDeviceItem = z.infer<typeof RemoteDeviceItemSchema>

export const PreferenceProposalItemSchema = z.object({
  id: z.string(),
  preference_key: z.string(),
  proposed_value: z.string(),
  rationale: z.string(),
  evidence_count: z.number().int().positive(),
  status: z.enum(['pending', 'approved', 'rejected', 'dismissed']),
})
export type PreferenceProposalItem = z.infer<typeof PreferenceProposalItemSchema>

export const McpServerItemSchema = z.object({
  id: z.string(),
  display_name: z.string(),
  version: z.string(),
  transport: z.enum(['stdio', 'https_readonly']),
  trust_tier: z.enum(['trusted_local', 'reviewed_readonly', 'untrusted']),
  data_destination: z.string(),
  allowed_scopes: z.array(z.string()),
  enabled: z.boolean(),
  quarantined: z.boolean(),
  quarantine_reason: z.string().nullable(),
  schema_pin_sha256: z.string().nullable(),
  pinned_tools: z.array(
    z.object({
      tool_name: z.string(),
      namespaced_tool_id: z.string(),
      read_only: z.boolean(),
      approved: z.boolean(),
    }),
  ),
})
export type McpServerItem = z.infer<typeof McpServerItemSchema>

export const EcosystemConnectorItemSchema = z.object({
  id: z.string(),
  kind: z.enum(['web_search', 'home_assistant', 'oauth_calendar', 'oauth_mail']),
  display_name: z.string(),
  endpoint_url: z.string(),
  allowed_scopes: z.array(z.string()),
  consent_acknowledged: z.boolean(),
  enabled: z.boolean(),
  revoked_at: z.string().nullable(),
})
export type EcosystemConnectorItem = z.infer<typeof EcosystemConnectorItemSchema>

export const BrokerStatusSchema = z.object({
  transport_ready: z.boolean(),
  core_connected: z.boolean(),
  core_port: z.number().int().nonnegative(),
  core_pid: z.number().int().positive().nullable(),
  core_error: z.string().nullable(),
  offline_default: z.boolean(),
  version: z.string(),
})
export type BrokerStatus = z.infer<typeof BrokerStatusSchema>

export const LiveVoiceStatusSchema = z.object({
  schema_version: z.literal(1),
  mode: z.enum(['muted', 'wake', 'active', 'ptt']),
  phase: z.enum([
    'muted',
    'standby_wake',
    'listening_command',
    'transcribing',
    'thinking',
    'speaking',
    'unavailable',
  ]),
  amplitude: z.number().min(0).max(1),
  stt_ready: z.boolean(),
  stt_model: z.string().nullable(),
  tts_ready: z.boolean(),
  tts_model: z.string().nullable(),
  mic_available: z.boolean(),
  active_command_window: z.boolean(),
  session_active: z.boolean().default(false),
  session_seconds_left: z.number().int().nonnegative().default(0),
  vad_engine: z.string().default('rms-fallback'),
  wake_engine: z.string().default('whisper-fallback'),
  last_transcript: z.string(),
  last_reply: z.string(),
  last_route_kind: z.string(),
  last_llm_called: z.boolean(),
  error: z.string().nullable(),
  llm_ready: z.boolean(),
  llm_starting: z.boolean(),
  llm_model: z.string().nullable(),
  llm_backend: z.string(),
  llm_note: z.string(),
})
export type LiveVoiceStatus = z.infer<typeof LiveVoiceStatusSchema>

export const MemoryListResponseSchema = z.object({
  schema_version: z.literal(1),
  memories: z.array(MemoryItemSchema),
})

export const MemoryCreateResponseSchema = z.object({
  schema_version: z.literal(1),
  memory: MemoryItemSchema,
})

export const ReminderListResponseSchema = z.object({
  schema_version: z.literal(1),
  reminders: z.array(ReminderItemSchema),
})

export const TaskListResponseSchema = z.object({
  schema_version: z.literal(1),
  tasks: z.array(TaskItemSchema),
})

export const KnowledgeRootListResponseSchema = z.object({
  schema_version: z.literal(1),
  roots: z.array(KnowledgeRootItemSchema),
})

export const KnowledgeRootCreateResponseSchema = z.object({
  schema_version: z.literal(1),
  root: KnowledgeRootItemSchema,
})

export const KnowledgeQueryResponseSchema = z.object({
  schema_version: z.literal(1),
  answer: z.string(),
  sufficient_evidence: z.boolean(),
  tools_disabled: z.boolean().default(true),
  citations: z.array(z.record(z.string(), z.unknown())).default([]),
})
export type KnowledgeQueryResponse = z.infer<typeof KnowledgeQueryResponseSchema>

export const ExpenseSummaryListResponseSchema = z.object({
  schema_version: z.literal(1),
  currencies: z.array(CurrencyExpenseSummarySchema),
})

export const AudioEndpointSchema = z.object({
  id: z.string(),
  name: z.string(),
  direction: z.enum(['input', 'output']),
  is_default: z.boolean(),
  form_factor: z.enum(['headphones', 'headset', 'speakers', 'microphone', 'unknown']),
})
export type AudioEndpoint = z.infer<typeof AudioEndpointSchema>

export const VoiceTimingTraceSchema = z.object({
  request_id: z.string(),
  transcript: z.string(),
  detected_language: z.string(),
  confidence: z.number(),
  route_kind: z.string(),
  stt_latency_ms: z.number(),
  ttfa_from_end_of_speech_ms: z.number().nullable(),
  total_perceived_ms: z.number().nullable(),
})

export const VoiceDiagnosticsResponseSchema = z.object({
  schema_version: z.literal(1),
  diagnostics: z.object({
    mode: z.string(),
    phase: z.string(),
    selected_input_device: z.string(),
    selected_output_device: z.string(),
    output_form_factor: z.string(),
    echo_guard_enabled: z.boolean(),
    echo_guard_reason: z.string(),
    voice_barge_in_allowed: z.boolean(),
    live_rms: z.number(),
    noise_floor_rms: z.number(),
    clipping_events: z.number().int().nonnegative(),
    queue_overflow_drops: z.number().int().nonnegative(),
    utterance_drops: z.number().int().nonnegative(),
    playback_generation: z.number().int().nonnegative(),
    vad_engine: z.string(),
    wake_engine: z.string(),
    stt_model: z.string().nullable(),
    stt_language_mode: z.string(),
    speech_rate: z.number(),
    installed_piper_voices: z.record(z.string(), z.string()),
    last_confidence: z.number(),
    last_detected_language: z.string(),
    recent_traces: z.array(VoiceTimingTraceSchema),
  }),
  endpoints: z.array(AudioEndpointSchema),
})
export type VoiceDiagnosticsResponse = z.infer<typeof VoiceDiagnosticsResponseSchema>
