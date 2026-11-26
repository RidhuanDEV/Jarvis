import { create } from 'zustand'
import type {
  ApprovalChallenge,
  CurrencyExpenseSummary,
  FpsTarget,
  HaEntityItem,
  HardwareCapabilitiesResponse,
  KnowledgeRootItem,
  LicenseArtifact,
  MachineState,
  MemoryItem,
  PreferenceProposalItem,
  ReminderItem,
  RemoteDeviceItem,
  RuntimeOwnershipMode,
  SequencedDomainEvent,
  StorageLocation,
  TaskItem,
  VisualQualityTier,
  WorkflowItem,
} from '../lib/contracts'
import { ApprovalChallengeSchema, MachineStateSchema } from '../lib/contracts'
import type { FrameTelemetrySnapshot } from '../lib/visualEngine'

export type NavigationTab =
  | 'command'
  | 'onboarding'
  | 'knowledge'
  | 'life'
  | 'workflows'
  | 'ecosystem'
  | 'memories'
  | 'reminders'
  | 'capabilities'
  | 'storage'
  | 'runtime'
  | 'licenses'

export interface PrivacyBadges {
  readonly micMode: 'muted' | 'ptt' | 'wake'
  readonly cameraActive: boolean
  readonly offlineMode: boolean
  readonly executionZone: 'direct_offline' | 'local_device' | 'private_lan'
}

export interface JarvisStoreState {
  activeTab: NavigationTab
  machineState: MachineState
  activeRequestId: string | null
  canceledRequestIds: ReadonlyArray<string>
  lastSeq: number
  staleEventsRejected: number
  statusAnnouncement: string
  privacy: PrivacyBadges
  qualityTier: VisualQualityTier
  fpsTarget: FpsTarget
  detectedRefreshHz: number
  runtimeOwnershipMode: RuntimeOwnershipMode
  pendingApproval: ApprovalChallenge | null
  capabilities: HardwareCapabilitiesResponse | null
  storageLocations: ReadonlyArray<StorageLocation>
  licenses: ReadonlyArray<LicenseArtifact>
  memories: ReadonlyArray<MemoryItem>
  reminders: ReadonlyArray<ReminderItem>
  knowledgeRoots: ReadonlyArray<KnowledgeRootItem>
  tasks: ReadonlyArray<TaskItem>
  expenseSummaries: ReadonlyArray<CurrencyExpenseSummary>
  workflows: ReadonlyArray<WorkflowItem>
  haEntities: ReadonlyArray<HaEntityItem>
  remoteGatewayEnabled: boolean
  remoteHostAvailable: boolean
  remoteDevices: ReadonlyArray<RemoteDeviceItem>
  preferenceProposals: ReadonlyArray<PreferenceProposalItem>
  activePersonaVerbosity: 'brief' | 'standard' | 'detailed'
  onboardingCompleted: boolean
  timezoneIana: string
  lastTurnReply: string
  frameTelemetry: FrameTelemetrySnapshot
  eventLog: ReadonlyArray<SequencedDomainEvent>

  setActiveTab: (tab: NavigationTab) => void
  setQualityTier: (tier: VisualQualityTier) => void
  setFpsTarget: (fps: FpsTarget) => void
  setDetectedRefreshHz: (hz: number) => void
  setRuntimeOwnershipMode: (mode: RuntimeOwnershipMode) => void
  toggleOfflineMode: () => void
  toggleMute: () => void
  startRequest: (requestId: string) => void
  cancelActiveRequest: () => void
  openApprovalChallenge: (challenge: ApprovalChallenge) => void
  resolvePendingApproval: (decision: 'approve' | 'reject' | 'expired') => void
  applySequencedEvent: (event: SequencedDomainEvent) => boolean
  setCapabilities: (data: HardwareCapabilitiesResponse) => void
  setStorageLocations: (locations: ReadonlyArray<StorageLocation>) => void
  setLicenses: (artifacts: ReadonlyArray<LicenseArtifact>) => void
  addMemory: (item: MemoryItem) => void
  approveMemoryProposal: (id: string) => void
  removeMemory: (id: string) => void
  addReminder: (item: ReminderItem) => void
  dismissReminder: (id: string) => void
  addKnowledgeRoot: (canonicalPath: string) => void
  revokeKnowledgeRoot: (id: string) => void
  addTask: (title: string) => void
  toggleTaskDone: (id: string) => void
  recordExpense: (input: {
    readonly amountMinor: number
    readonly currencyIso: string
    readonly kind: 'expense' | 'refund'
  }) => void
  addWorkflow: (name: string) => void
  setCameraActive: (active: boolean) => void
  addHaEntity: (entityId: string, friendlyName: string) => boolean
  toggleRemoteGateway: () => void
  toggleRemoteHostAvailable: () => void
  revokeRemoteDevice: (deviceId: string) => void
  decidePreferenceProposal: (id: string, decision: 'approve' | 'reject') => void
  completeOnboarding: (timezoneIana: string) => void
  setLastTurnReply: (reply: string, state?: MachineState) => void
  updateFrameTelemetry: (telemetry: FrameTelemetrySnapshot) => void
}

const INITIAL_TELEMETRY: FrameTelemetrySnapshot = {
  renderedFrames: 0,
  measuredFps: 0,
  p50Ms: 0,
  p95Ms: 0,
  droppedFrames: 0,
}

export const useJarvisStore = create<JarvisStoreState>((set, get) => ({
  activeTab: 'command',
  machineState: 'Offline',
  activeRequestId: null,
  canceledRequestIds: [],
  lastSeq: 0,
  staleEventsRejected: 0,
  statusAnnouncement: 'J.A.R.V.I.S. siap dalam mode lokal offline. Mikrofon dibisukan.',
  privacy: {
    micMode: 'muted',
    cameraActive: false,
    offlineMode: true,
    executionZone: 'direct_offline',
  },
  qualityTier: 'balanced',
  fpsTarget: 'auto',
  detectedRefreshHz: 60,
  runtimeOwnershipMode: 'none',
  pendingApproval: null,
  capabilities: null,
  storageLocations: [],
  licenses: [],
  memories: [],
  reminders: [],
  knowledgeRoots: [],
  tasks: [],
  expenseSummaries: [],
  workflows: [],
  haEntities: [
    {
      entity_id: 'light.desk_lamp',
      domain: 'light',
      friendly_name: 'Lampu Meja Kerja',
      allowed_actions: ['read_state', 'turn_on', 'turn_off'],
      enabled: true,
    },
  ],
  remoteGatewayEnabled: false,
  remoteHostAvailable: true,
  remoteDevices: [
    {
      id: 'dev-sample-mobile',
      label: 'Paired Mobile Client (Scoped)',
      scopes: ['remote.status.read', 'remote.chat.send', 'remote.reminder.read'],
      revoked_at: null,
    },
  ],
  preferenceProposals: [
    {
      id: 'prop-verbosity-brief',
      preference_key: 'persona.verbosity',
      proposed_value: 'brief',
      rationale: 'Terdeteksi 3 koreksi eksplisit lokal agar jawaban lebih ringkas.',
      evidence_count: 3,
      status: 'pending',
    },
  ],
  activePersonaVerbosity: 'standard',
  onboardingCompleted: false,
  timezoneIana: 'UTC',
  lastTurnReply: '',
  frameTelemetry: INITIAL_TELEMETRY,
  eventLog: [],

  setActiveTab: (tab) => set({ activeTab: tab }),

  setQualityTier: (qualityTier) =>
    set({
      qualityTier,
      statusAnnouncement: `Tier visual diperbarui ke ${qualityTier}.`,
    }),

  setFpsTarget: (fpsTarget) =>
    set({
      fpsTarget,
      statusAnnouncement: `Target FPS diperbarui ke ${fpsTarget}.`,
    }),

  setDetectedRefreshHz: (hz) =>
    set({ detectedRefreshHz: Number.isFinite(hz) && hz >= 24 ? hz : 60 }),

  setRuntimeOwnershipMode: (runtimeOwnershipMode) =>
    set((s) => ({
      runtimeOwnershipMode,
      privacy: {
        ...s.privacy,
        executionZone:
          runtimeOwnershipMode === 'none'
            ? 'direct_offline'
            : runtimeOwnershipMode === 'authorized_lan'
              ? 'private_lan'
              : 'local_device',
      },
      statusAnnouncement: `Mode kepemilikan runtime: ${runtimeOwnershipMode}.`,
    })),

  toggleOfflineMode: () =>
    set((s) => {
      const nextOffline = !s.privacy.offlineMode
      return {
        privacy: { ...s.privacy, offlineMode: nextOffline },
        machineState: nextOffline ? 'Offline' : s.privacy.micMode === 'muted' ? 'Muted' : 'Idle',
        statusAnnouncement: nextOffline
          ? 'Mode offline aktif. Seluruh konektor jaringan diputus.'
          : 'Mode lokal dengan jaringan opsional diaktifkan.',
      }
    }),

  toggleMute: () =>
    set((s) => {
      const nextMic = s.privacy.micMode === 'muted' ? 'ptt' : 'muted'
      return {
        privacy: { ...s.privacy, micMode: nextMic },
        machineState: nextMic === 'muted' ? 'Muted' : s.privacy.offlineMode ? 'Offline' : 'Idle',
        statusAnnouncement:
          nextMic === 'muted'
            ? 'Mikrofon dibisukan.'
            : 'Mode Push-to-Talk aktif (tidak merekam kontinu).',
      }
    }),

  startRequest: (requestId) =>
    set({
      activeRequestId: requestId,
      machineState: 'Thinking',
      statusAnnouncement: `Memproses permintaan ${requestId}.`,
    }),

  cancelActiveRequest: () =>
    set((s) => {
      const canceled = s.activeRequestId
        ? [...s.canceledRequestIds.slice(-31), s.activeRequestId]
        : s.canceledRequestIds
      return {
        activeRequestId: null,
        canceledRequestIds: canceled,
        pendingApproval: null,
        privacy: { ...s.privacy, cameraActive: false },
        machineState: s.privacy.offlineMode ? 'Offline' : 'Idle',
        statusAnnouncement: 'Permintaan aktif, kamera, dan persetujuan tertunda dibatalkan.',
      }
    }),

  openApprovalChallenge: (challenge) =>
    set({
      pendingApproval: challenge,
      machineState: 'Approval',
      statusAnnouncement: `Persetujuan R2 diperlukan untuk ${challenge.tool_id}.`,
    }),

  resolvePendingApproval: (decision) =>
    set((s) => ({
      pendingApproval: null,
      machineState:
        decision === 'approve'
          ? 'Executing'
          : decision === 'expired'
            ? 'Error'
            : s.privacy.offlineMode
              ? 'Offline'
              : 'Idle',
      statusAnnouncement:
        decision === 'approve'
          ? 'Persetujuan R2 dikonfirmasi secara lokal; menunggu verifikasi adapter.'
          : decision === 'expired'
            ? 'Persetujuan R2 kedaluwarsa (60 detik) dan dibatalkan.'
            : 'Persetujuan R2 ditolak oleh pemilik.',
    })),

  applySequencedEvent: (event) => {
    const state = get()
    // Monotonic sequence guard: drop duplicate or out-of-order seq
    if (event.seq <= state.lastSeq) {
      set({ staleEventsRejected: state.staleEventsRejected + 1 })
      return false
    }
    // Stale request guard: drop late events belonging to already canceled or superseded requests
    if (event.request_id !== null) {
      if (state.canceledRequestIds.includes(event.request_id)) {
        set({ staleEventsRejected: state.staleEventsRejected + 1 })
        return false
      }
      if (state.activeRequestId !== null && event.request_id !== state.activeRequestId) {
        set({ staleEventsRejected: state.staleEventsRejected + 1 })
        return false
      }
    }

    let nextMachineState: MachineState = state.machineState
    let nextApproval = state.pendingApproval
    let nextAnnouncement = state.statusAnnouncement

    if (event.type === 'request.state_changed') {
      const parsedState = MachineStateSchema.safeParse(event.payload['state'])
      if (parsedState.success) {
        nextMachineState = parsedState.data
        nextAnnouncement = `Status mesin: ${parsedState.data}.`
      }
    } else if (event.type === 'approval.required') {
      const parsedApproval = ApprovalChallengeSchema.safeParse(event.payload)
      if (parsedApproval.success) {
        nextApproval = parsedApproval.data
        nextMachineState = 'Approval'
        nextAnnouncement = `Persetujuan R2 diperlukan untuk ${parsedApproval.data.tool_id}.`
      }
    } else if (event.type === 'session.locked') {
      nextApproval = null
      nextMachineState = 'Muted'
      nextAnnouncement = 'Sesi terkunci — seluruh persetujuan tertunda dibatalkan.'
    }

    set({
      lastSeq: event.seq,
      machineState: nextMachineState,
      pendingApproval: nextApproval,
      statusAnnouncement: nextAnnouncement,
      eventLog: [event, ...state.eventLog.slice(0, 49)],
    })
    return true
  },

  setCapabilities: (capabilities) => {
    const primary = capabilities.snapshot.displays.find((d) => d.is_primary) ?? capabilities.snapshot.displays[0]
    set({
      capabilities,
      detectedRefreshHz: primary ? primary.refresh_hz : 60,
    })
  },

  setStorageLocations: (storageLocations) => set({ storageLocations }),
  setLicenses: (licenses) => set({ licenses }),
  addMemory: (item) =>
    set((s) => ({
      memories: [item, ...s.memories],
      statusAnnouncement: `Memori '${item.kind}' disimpan secara eksplisit.`,
    })),
  approveMemoryProposal: (id) =>
    set((s) => ({
      memories: s.memories.map((m) =>
        m.id === id ? { ...m, status: 'active', revision: m.revision + 1 } : m,
      ),
      statusAnnouncement: 'Proposal preferensi disetujui menjadi memori aktif.',
    })),
  removeMemory: (id) =>
    set((s) => ({
      memories: s.memories.filter((m) => m.id !== id),
      statusAnnouncement: 'Memori dihapus dan dicatat pada deletion_ledger.',
    })),
  addReminder: (item) =>
    set((s) => ({
      reminders: [...s.reminders, item],
      statusAnnouncement: `Pengingat '${item.title}' dijadwalkan (${item.timezone_iana}).`,
    })),
  dismissReminder: (id) =>
    set((s) => ({
      reminders: s.reminders.map((r) =>
        r.id === id ? { ...r, state: 'dismissed', revision: r.revision + 1 } : r,
      ),
      statusAnnouncement: 'Pengingat ditandai selesai.',
    })),
  addKnowledgeRoot: (canonicalPath) =>
    set((s) => ({
      knowledgeRoots: [
        ...s.knowledgeRoots,
        { id: `root-${Date.now()}`, canonical_path: canonicalPath, enabled: true, revision: 1 },
      ],
      statusAnnouncement: `Folder pengetahuan opt-in ditambahkan: ${canonicalPath}.`,
    })),
  revokeKnowledgeRoot: (id) =>
    set((s) => ({
      knowledgeRoots: s.knowledgeRoots.map((r) =>
        r.id === id ? { ...r, enabled: false, revision: r.revision + 1 } : r,
      ),
      statusAnnouncement: 'Akses folder pengetahuan dicabut dan indeks terkait dijadwalkan bersih.',
    })),
  addTask: (title) =>
    set((s) => ({
      tasks: [...s.tasks, { id: `task-${Date.now()}`, title, status: 'open', revision: 1 }],
      statusAnnouncement: `Tugas '${title}' disimpan lokal.`,
    })),
  toggleTaskDone: (id) =>
    set((s) => ({
      tasks: s.tasks.map((t) =>
        t.id === id
          ? { ...t, status: t.status === 'completed' ? 'open' : 'completed', revision: t.revision + 1 }
          : t,
      ),
    })),
  recordExpense: ({ amountMinor, currencyIso, kind }) =>
    set((s) => {
      const iso = currencyIso.toUpperCase()
      const existing = s.expenseSummaries.find((e) => e.currency_iso === iso)
      const expDelta = kind === 'expense' ? amountMinor : 0
      const refDelta = kind === 'refund' ? amountMinor : 0
      const updated = existing
        ? s.expenseSummaries.map((e) =>
            e.currency_iso === iso
              ? {
                  ...e,
                  total_expense_minor: e.total_expense_minor + expDelta,
                  total_refund_minor: e.total_refund_minor + refDelta,
                  net_spend_minor: e.net_spend_minor + expDelta - refDelta,
                  transaction_count: e.transaction_count + 1,
                }
              : e,
          )
        : [
            ...s.expenseSummaries,
            {
              currency_iso: iso,
              total_expense_minor: expDelta,
              total_refund_minor: refDelta,
              net_spend_minor: expDelta - refDelta,
              transaction_count: 1,
            },
          ]
      return {
        expenseSummaries: updated,
        statusAnnouncement: `Pengeluaran ${amountMinor} minor ${iso} dicatat terpisah tanpa konversi kurs otomatis.`,
      }
    }),
  addWorkflow: (name) =>
    set((s) => ({
      workflows: [
        ...s.workflows,
        {
          id: `wf-${Date.now()}`,
          name,
          step_count: 2,
          revision: 1,
          bound_hash: `h${Date.now().toString(16).padEnd(63, '0')}`,
        },
      ],
      statusAnnouncement: `Workflow deklaratif '${name}' disimpan (≤ 5 langkah, 0 R3).`,
    })),
  setCameraActive: (cameraActive) =>
    set((s) => ({
      privacy: { ...s.privacy, cameraActive },
      statusAnnouncement: cameraActive
        ? 'Kamera on-demand aktif dengan indikator visual (RAM-only, tanpa rekam latar belakang).'
        : 'Kamera dihentikan dan buffer memori dibersihkan.',
    })),
  addHaEntity: (entityId, friendlyName) => {
    const cleaned = entityId.trim().toLowerCase()
    const bannedPrefix =
      cleaned.startsWith('lock.') ||
      cleaned.startsWith('alarm_control_panel.') ||
      cleaned.startsWith('climate.') ||
      cleaned.startsWith('valve.') ||
      cleaned.startsWith('cover.') ||
      /(?:lock|alarm|heater|gas|garage|medical)/.test(cleaned)
    if (bannedPrefix || !cleaned.includes('.')) {
      set({
        statusAnnouncement: `Entitas '${entityId}' diblokir keras (R3 safety-critical, FR-IOT-03).`,
      })
      return false
    }
    const domain = cleaned.split('.')[0] ?? 'light'
    set((s) => ({
      haEntities: [
        ...s.haEntities,
        {
          entity_id: cleaned,
          domain,
          friendly_name: friendlyName.trim() || cleaned,
          allowed_actions: ['read_state', 'turn_on', 'turn_off'],
          enabled: true,
        },
      ],
      statusAnnouncement: `Entitas Home Assistant '${cleaned}' ditambahkan ke allowlist aman.`,
    }))
    return true
  },
  toggleRemoteGateway: () =>
    set((s) => ({
      remoteGatewayEnabled: !s.remoteGatewayEnabled,
      statusAnnouncement: !s.remoteGatewayEnabled
        ? 'Gateway remote privat diaktifkan (hanya VPN/TLS privat, tanpa port publik).'
        : 'Gateway remote privat dinonaktifkan.',
    })),
  toggleRemoteHostAvailable: () =>
    set((s) => ({
      remoteHostAvailable: !s.remoteHostAvailable,
      statusAnnouncement: !s.remoteHostAvailable
        ? 'Host desktop kembali online untuk klien mobile berizin.'
        : 'Host desktop disimulasikan tidur/offline — klien mobile menerima status Host Unreachable tanpa antre mutasi.',
    })),
  revokeRemoteDevice: (deviceId) =>
    set((s) => ({
      remoteDevices: s.remoteDevices.map((d) =>
        d.id === deviceId ? { ...d, revoked_at: new Date().toISOString() } : d,
      ),
      statusAnnouncement: `Perangkat remote '${deviceId}' dicabut seketika.`,
    })),
  decidePreferenceProposal: (id, decision) =>
    set((s) => {
      const target = s.preferenceProposals.find((p) => p.id === id)
      const nextVerbosity =
        decision === 'approve' &&
        target?.preference_key === 'persona.verbosity' &&
        (target.proposed_value === 'brief' ||
          target.proposed_value === 'standard' ||
          target.proposed_value === 'detailed')
          ? target.proposed_value
          : s.activePersonaVerbosity
      return {
        preferenceProposals: s.preferenceProposals.map((p) =>
          p.id === id ? { ...p, status: decision === 'approve' ? 'approved' : 'rejected' } : p,
        ),
        activePersonaVerbosity: nextVerbosity,
        statusAnnouncement:
          decision === 'approve'
            ? 'Proposal preferensi disetujui secara eksplisit dan diterapkan.'
            : 'Proposal preferensi ditolak — konfigurasi aktif tidak berubah.',
      }
    }),
  completeOnboarding: (timezoneIana) =>
    set({
      onboardingCompleted: true,
      timezoneIana,
      activeTab: 'command',
      statusAnnouncement: `Onboarding 10 langkah selesai (zona waktu ${timezoneIana}).`,
    }),
  setLastTurnReply: (reply, state) =>
    set((s) => ({
      lastTurnReply: reply,
      machineState: state ?? s.machineState,
      statusAnnouncement: reply,
    })),
  updateFrameTelemetry: (frameTelemetry) => set({ frameTelemetry }),
}))
