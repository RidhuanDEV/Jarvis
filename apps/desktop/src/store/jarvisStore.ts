import { create } from 'zustand'
import type {
  ApprovalChallenge,
  FpsTarget,
  HardwareCapabilitiesResponse,
  LicenseArtifact,
  MachineState,
  RuntimeOwnershipMode,
  SequencedDomainEvent,
  StorageLocation,
  VisualQualityTier,
} from '../lib/contracts'
import { ApprovalChallengeSchema, MachineStateSchema } from '../lib/contracts'
import type { FrameTelemetrySnapshot } from '../lib/visualEngine'

export type NavigationTab = 'command' | 'capabilities' | 'storage' | 'runtime' | 'licenses'

export interface PrivacyBadges {
  readonly micMode: 'muted' | 'ptt' | 'wake'
  readonly cameraActive: false
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
        machineState: s.privacy.offlineMode ? 'Offline' : 'Idle',
        statusAnnouncement: 'Permintaan aktif dan persetujuan tertunda dibatalkan.',
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
  updateFrameTelemetry: (frameTelemetry) => set({ frameTelemetry }),
}))
