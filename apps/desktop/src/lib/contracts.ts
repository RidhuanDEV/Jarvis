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
