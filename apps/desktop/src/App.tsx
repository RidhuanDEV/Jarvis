import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import {
  Activity,
  ArrowUpRight,
  Bell,
  BookOpen,
  Brain,
  CalendarCheck2,
  Compass,
  Cpu,
  GitBranch,
  HardDrive,
  Layers,
  Mic,
  MicOff,
  Radio,
  Scale,
  Send,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Square,
  Wifi,
  WifiOff,
} from 'lucide-react'
import { ApprovalDialog } from './components/ApprovalDialog'
import { EcosystemPanel } from './components/EcosystemPanels'
import {
  CapabilitiesPanel,
  LicenseInventoryPanel,
  RuntimeVisualPanel,
  StorageManagerPanel,
} from './components/FoundationPanels'
import { MemoryVaultPanel, RemindersPanel } from './components/IntelligencePanels'
import { OnboardingWizard } from './components/OnboardingWizard'
import { OrbitalCore } from './components/OrbitalCore'
import {
  KnowledgePanel,
  PersonalLifePanel,
  WorkflowsPanel,
} from './components/ProductivityPanels'
import {
  armLiveVoiceMode,
  cancelBrokerActiveRequest,
  dispatchApprovalDecision,
  dispatchCommandTurn,
  fetchLiveVoiceStatus,
  fetchVoiceDiagnostics,
  loadFoundationData,
  loadHydratedUserData,
  persistExpenseRecord,
  persistHaEntityAdd,
  persistKnowledgeRootAdd,
  persistKnowledgeRootRevoke,
  persistMemoryCreate,
  persistMemoryDelete,
  persistOnboardingCompletion,
  persistPreferenceDecision,
  persistReminderCreate,
  persistRemoteDeviceRevoke,
  persistTaskCreate,
  queryKnowledgeLive,
  replayVoiceTranscript,
  selectBrokerAudioDevices,
  setBrokerSpeechRate,
  stopLiveSpeakingAudio,
  subscribeToBrokerEvents,
} from './lib/brokerClient'
import type {
  ApprovalChallenge,
  BrokerStatus,
  LiveVoiceStatus,
  MachineState,
  VoiceDiagnosticsResponse,
} from './lib/contracts'
import { useJarvisStore, type NavigationTab } from './store/jarvisStore'

const NAV_GROUPS: ReadonlyArray<{
  readonly heading: string
  readonly items: ReadonlyArray<{ readonly id: NavigationTab; readonly label: string }>
}> = [
  {
    heading: 'Operations',
    items: [
      { id: 'command', label: 'Command Center' },
      { id: 'onboarding', label: 'Onboarding (10 Steps)' },
      { id: 'workflows', label: 'Workflows' },
      { id: 'reminders', label: 'Reminders' },
    ],
  },
  {
    heading: 'Intelligence',
    items: [
      { id: 'knowledge', label: 'Knowledge (Hybrid RAG)' },
      { id: 'memories', label: 'Memory Vault' },
      { id: 'life', label: 'Personal Life' },
    ],
  },
  {
    heading: 'Ecosystem & System',
    items: [
      { id: 'ecosystem', label: 'Ecosystem & Remote (R3)' },
      { id: 'capabilities', label: 'Hardware Discovery' },
      { id: 'storage', label: 'Storage (11 Roots)' },
      { id: 'runtime', label: 'Runtime & Visuals' },
      { id: 'licenses', label: 'Licenses & SBOM' },
    ],
  },
]

const QUICK_COMMANDS: ReadonlyArray<{ readonly label: string; readonly prompt: string }> = [
  { label: 'Jam sekarang', prompt: 'Hey Jarvis, pukul berapa sekarang ya?' },
  { label: 'Atur volume 40%', prompt: 'Atur volume ke 40 persen' },
  { label: 'Uji tolak hapus (R3)', prompt: 'Hapus file laporan.pdf permanen' },
]

export function App() {
  const {
    activeTab,
    machineState,
    activeRequestId,
    lastSeq,
    staleEventsRejected,
    statusAnnouncement,
    privacy,
    qualityTier,
    fpsTarget,
    detectedRefreshHz,
    runtimeOwnershipMode,
    pendingApproval,
    capabilities,
    storageLocations,
    licenses,
    memories,
    reminders,
    knowledgeRoots,
    tasks,
    expenseSummaries,
    workflows,
    haEntities,
    remoteGatewayEnabled,
    remoteHostAvailable,
    remoteDevices,
    preferenceProposals,
    activePersonaVerbosity,
    timezoneIana,
    lastTurnReply,
    lastTurnReplyAt,
    frameTelemetry,
    setActiveTab,
    setQualityTier,
    setFpsTarget,
    setRuntimeOwnershipMode,
    toggleOfflineMode,
    toggleMute,
    cancelActiveRequest,
    openApprovalChallenge,
    resolvePendingApproval,
    applySequencedEvent,
    hydratePersistedData,
    setCapabilities,
    setStorageLocations,
    setLicenses,
    addMemory,
    replaceMemoryId,
    approveMemoryProposal,
    removeMemory,
    addReminder,
    dismissReminder,
    addKnowledgeRoot,
    replaceKnowledgeRootId,
    revokeKnowledgeRoot,
    addTask,
    toggleTaskDone,
    recordExpense,
    addWorkflow,
    setCameraActive,
    addHaEntity,
    toggleRemoteGateway,
    toggleRemoteHostAvailable,
    revokeRemoteDevice,
    decidePreferenceProposal,
    completeOnboarding,
    setLastTurnReply,
    updateFrameTelemetry,
  } = useJarvisStore()

  const [turnInput, setTurnInput] = useState('')
  const [brokerStatus, setBrokerStatus] = useState<BrokerStatus | null>(null)
  const [brokerSource, setBrokerSource] = useState<'tauri_broker' | 'preview_fixture'>('preview_fixture')
  const [liveVoice, setLiveVoice] = useState<LiveVoiceStatus | null>(null)
  const [voiceDiagnostics, setVoiceDiagnostics] = useState<VoiceDiagnosticsResponse | null>(null)
  const [showKeyboardFallback, setShowKeyboardFallback] = useState(false)
  const liveVoiceReplyMetaRef = useRef<{ text: string; updatedAt: number }>({
    text: '',
    updatedAt: 0,
  })

  useEffect(() => {
    let active = true
    void loadFoundationData().then((data) => {
      if (!active) return
      setCapabilities(data.capabilities)
      setStorageLocations(data.storageLocations)
      setLicenses(data.licenses)
      setBrokerStatus(data.brokerStatus)
      setBrokerSource(data.source)
    })
    return () => {
      active = false
    }
  }, [setCapabilities, setStorageLocations, setLicenses])

  // B08: Hydrate persisted user data & subscribe to authenticated Core SSE cursor bridge
  useEffect(() => {
    if (brokerSource !== 'tauri_broker') return
    let active = true
    let cleanupEvents: (() => void) | null = null

    void loadHydratedUserData().then((hydrated) => {
      if (!active || !hydrated) return
      hydratePersistedData(hydrated)
    })

    void subscribeToBrokerEvents((ev) => {
      if (!active) return
      applySequencedEvent(ev)
    }).then((unsub) => {
      if (!active) {
        unsub()
      } else {
        cleanupEvents = unsub
      }
    })

    const poll = () => {
      void fetchLiveVoiceStatus().then((vs) => {
        if (!active || !vs) return
        if (vs.last_reply && vs.last_reply !== liveVoiceReplyMetaRef.current.text) {
          liveVoiceReplyMetaRef.current = { text: vs.last_reply, updatedAt: Date.now() }
        }
        setLiveVoice(vs)
      })
    }
    const pollDiag = () => {
      void fetchVoiceDiagnostics().then((vd) => {
        if (active && vd) setVoiceDiagnostics(vd)
      })
    }
    poll()
    pollDiag()
    const timer = window.setInterval(poll, 350)
    const diagTimer = window.setInterval(pollDiag, 2000)
    return () => {
      active = false
      window.clearInterval(timer)
      window.clearInterval(diagTimer)
      if (cleanupEvents) cleanupEvents()
    }
  }, [brokerSource, applySequencedEvent, hydratePersistedData])

  const handleArmVoice = useCallback((mode: 'wake' | 'active' | 'ptt' | 'muted') => {
    if (mode !== 'muted') {
      setShowKeyboardFallback(false)
    }
    void armLiveVoiceMode(mode).then((vs) => {
      if (vs) setLiveVoice(vs)
    })
  }, [])

  const effectiveMachineState: MachineState = liveVoice
    ? liveVoice.phase === 'listening_command'
      ? 'Listening'
      : liveVoice.phase === 'transcribing'
        ? 'Transcribing'
        : liveVoice.phase === 'thinking'
          ? 'Thinking'
          : liveVoice.phase === 'speaking'
            ? 'Speaking'
            : liveVoice.phase === 'standby_wake'
              ? 'Idle'
              : liveVoice.phase === 'muted'
                ? 'Muted'
                : machineState
    : machineState

  const isVoiceArmed = liveVoice
    ? liveVoice.mode === 'wake' || liveVoice.mode === 'active' || liveVoice.mode === 'ptt'
    : privacy.micMode !== 'muted'
  const showTextForm = showKeyboardFallback || !isVoiceArmed

  const handleApprove = useCallback(
    (challenge: ApprovalChallenge) => {
      void dispatchApprovalDecision({
        approvalId: challenge.approval_id,
        decision: 'approve',
        nonce: challenge.nonce,
        boundHash: challenge.bound_hash,
      }).finally(() => resolvePendingApproval('approve'))
    },
    [resolvePendingApproval],
  )

  const handleReject = useCallback(
    (challenge: ApprovalChallenge) => {
      void dispatchApprovalDecision({
        approvalId: challenge.approval_id,
        decision: 'reject',
        nonce: challenge.nonce,
        boundHash: challenge.bound_hash,
      }).finally(() => resolvePendingApproval('reject'))
    },
    [resolvePendingApproval],
  )

  const handleExpire = useCallback(
    (_challenge: ApprovalChallenge) => {
      resolvePendingApproval('expired')
    },
    [resolvePendingApproval],
  )

  const submitUtterance = (raw: string) => {
    const trimmed = raw.trim()
    if (!trimmed) return
    setTurnInput('')
    void dispatchCommandTurn(trimmed).then((res) => {
      setLastTurnReply(res.reply, res.approval ? 'Approval' : 'Success')
      if (res.approval) {
        openApprovalChallenge(res.approval)
      }
    })
  }

  const handleTurnSubmit = (ev: React.FormEvent) => {
    ev.preventDefault()
    submitUtterance(turnInput)
  }

  const triggerSampleR2Preview = () => {
    openApprovalChallenge({
      approval_id: 'preview-r2-storage-migrate',
      action_run_id: 'preview-run-1',
      tool_id: 'storage.location.migrate',
      tool_version: 1,
      bound_hash: 'a'.repeat(64),
      nonce: 'n'.repeat(32),
      expires_at: new Date(Date.now() + 60_000).toISOString(),
      summary:
        'Pratinjau dialog persetujuan lokal R2: memindahkan lokasi penyimpanan cache dengan verifikasi SHA-256 dan rollback otomatis.',
      before_preview: 'cache -> <OS_CACHE>/Jarvis/cache',
      after_preview: 'cache -> <SELECTED_LOCAL_VOLUME>/JarvisCache',
    })
  }

  const primaryGpu = capabilities?.snapshot.gpus[0]

  return (
    <div className="jarvis-stage-bg flex min-h-screen flex-col">
      {/* Screen-reader polite state announcements (10-UX-DESIGN.md §6) */}
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {statusAnnouncement}
      </div>

      {/* Explicit privacy & execution boundary top instrument header */}
      <header className="jarvis-topbar sticky top-0 z-30 flex flex-wrap items-center justify-between gap-3 px-5 py-3">
        <div className="flex items-center gap-3">
          {/* Precision Orbital Brand Mark */}
          <svg viewBox="0 0 32 32" className="h-7 w-7 shrink-0" aria-hidden="true">
            <circle
              cx="16"
              cy="16"
              r="13"
              fill="rgba(87, 223, 255, 0.08)"
              stroke="#57dfff"
              strokeWidth="1.6"
              strokeDasharray="16 6 5 6"
              strokeLinecap="round"
            />
            <circle cx="16" cy="16" r="7.5" fill="none" stroke="#5eead4" strokeWidth="1.2" strokeOpacity="0.7" />
            <circle cx="16" cy="16" r="3" fill="#57dfff" />
          </svg>
          <div>
            <div className="flex items-center gap-2.5">
              <span
                className="font-display text-sm font-bold tracking-[0.22em]"
                style={{ color: 'var(--accent-core)' }}
              >
                J.A.R.V.I.S.
              </span>
              <span
                data-testid="badge-core-ipc"
                title={
                  brokerStatus?.core_connected
                    ? `Core PID ${brokerStatus.core_pid ?? '?'} @ 127.0.0.1:${brokerStatus.core_port}`
                    : brokerStatus?.core_error ?? 'Standalone browser preview fixture'
                }
                className="font-mono-tabular inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px]"
                style={{
                  borderColor:
                    brokerSource === 'tauri_broker' ? 'rgba(94, 234, 212, 0.45)' : 'var(--border-subtle)',
                  backgroundColor:
                    brokerSource === 'tauri_broker' ? 'var(--status-ok-dim)' : 'rgba(6, 11, 20, 0.55)',
                  color: brokerSource === 'tauri_broker' ? 'var(--status-ok)' : 'var(--text-muted)',
                }}
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{
                    backgroundColor:
                      brokerSource === 'tauri_broker' ? 'var(--status-ok)' : 'var(--text-muted)',
                  }}
                />
                {brokerSource === 'tauri_broker'
                  ? `CORE: LIVE (:${brokerStatus?.core_port ?? 0})`
                  : 'MODE: PREVIEW'}
              </span>
            </div>
            <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              Personal Intelligence OS · v0.2.2
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          <span
            data-testid="badge-mic"
            className="font-mono-tabular inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1"
            style={{
              borderColor: isVoiceArmed ? 'rgba(87, 223, 255, 0.45)' : 'var(--border-subtle)',
              backgroundColor: isVoiceArmed ? 'var(--accent-core-dim)' : 'rgba(6, 11, 20, 0.5)',
              color: isVoiceArmed ? 'var(--accent-core)' : 'var(--text-secondary)',
            }}
          >
            {!isVoiceArmed ? (
              <MicOff className="h-3 w-3" aria-hidden="true" />
            ) : (
              <Mic className="h-3 w-3" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
            )}
            MIC:{' '}
            {liveVoice
              ? liveVoice.mode === 'wake'
                ? 'HEY JARVIS'
                : liveVoice.mode.toUpperCase()
              : privacy.micMode.toUpperCase()}
          </span>

          <span
            data-testid="badge-llm"
            title={liveVoice?.llm_note ?? 'Local AI Engine status'}
            className="font-mono-tabular inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1"
            style={{
              borderColor: liveVoice?.llm_ready
                ? 'rgba(94, 234, 212, 0.45)'
                : liveVoice?.llm_starting
                  ? 'rgba(255, 190, 105, 0.45)'
                  : 'var(--border-subtle)',
              backgroundColor: liveVoice?.llm_ready
                ? 'var(--status-ok-dim)'
                : liveVoice?.llm_starting
                  ? 'var(--status-warn-dim)'
                  : 'rgba(6, 11, 20, 0.5)',
              color: liveVoice?.llm_ready
                ? 'var(--status-ok)'
                : liveVoice?.llm_starting
                  ? 'var(--status-warn)'
                  : 'var(--text-secondary)',
            }}
          >
            {liveVoice?.llm_ready
              ? `LLM: ${liveVoice.llm_model ?? 'LOCAL'} (${liveVoice.llm_backend.toUpperCase()})`
              : liveVoice?.llm_starting
                ? 'LLM: MEMUAT GPU...'
                : 'LLM: DIRECT MODE'}
          </span>

          <span
            data-testid="badge-cam"
            className="font-mono-tabular inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1"
            style={{
              borderColor: privacy.cameraActive ? 'rgba(255, 190, 105, 0.45)' : 'var(--border-subtle)',
              backgroundColor: privacy.cameraActive ? 'var(--status-warn-dim)' : 'rgba(6, 11, 20, 0.5)',
              color: privacy.cameraActive ? 'var(--status-warn)' : 'var(--text-secondary)',
            }}
          >
            {privacy.cameraActive ? 'CAM: ON-DEMAND' : 'CAM: OFF'}
          </span>

          <span
            data-testid="badge-network"
            className="font-mono-tabular inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1"
            style={{
              borderColor: privacy.offlineMode ? 'rgba(94, 234, 212, 0.4)' : 'rgba(255, 190, 105, 0.45)',
              backgroundColor: privacy.offlineMode ? 'var(--status-ok-dim)' : 'var(--status-warn-dim)',
              color: privacy.offlineMode ? 'var(--status-ok)' : 'var(--status-warn)',
            }}
          >
            {privacy.offlineMode ? (
              <WifiOff className="h-3 w-3" aria-hidden="true" />
            ) : (
              <Wifi className="h-3 w-3" aria-hidden="true" />
            )}
            {privacy.offlineMode ? 'OFFLINE' : 'LOCAL + OPTIONAL NET'}
          </span>

          <span
            className="font-mono-tabular rounded-full border px-2.5 py-1"
            style={{
              borderColor: 'var(--border-subtle)',
              backgroundColor: 'rgba(6, 11, 20, 0.5)',
              color: 'var(--text-muted)',
            }}
          >
            ZONE: {privacy.executionZone.toUpperCase()}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              toggleMute()
              handleArmVoice(isVoiceArmed ? 'muted' : 'wake')
            }}
            className="rounded-lg border px-3 py-1.5 text-xs font-medium transition-all hover:bg-[#1c304d] active:scale-[0.98]"
            style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
          >
            {!isVoiceArmed ? 'Aktifkan Hey Jarvis' : 'Bisukan Mic'}
          </button>
          <button
            type="button"
            onClick={toggleOfflineMode}
            className="rounded-lg border px-3 py-1.5 text-xs font-medium transition-all hover:bg-[#1c304d] active:scale-[0.98]"
            style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
          >
            {privacy.offlineMode ? 'Buka Jaringan Opsional' : 'Aktifkan Offline'}
          </button>
          <button
            type="button"
            onClick={() => {
              cancelActiveRequest()
              void cancelBrokerActiveRequest(activeRequestId)
              void stopLiveSpeakingAudio()
            }}
            className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-semibold transition-all hover:brightness-110 active:scale-[0.98]"
            style={{
              borderColor: 'rgba(255, 115, 124, 0.35)',
              backgroundColor: 'var(--status-danger-dim)',
              color: 'var(--status-danger)',
            }}
          >
            <Square className="h-3 w-3" aria-hidden="true" />
            Stop
          </button>
        </div>
      </header>

      <div className="mx-auto grid w-full max-w-[1360px] flex-1 gap-6 px-5 py-6 md:grid-cols-[236px_1fr]">
        <nav aria-label="Navigasi utama" className="space-y-5">
          {NAV_GROUPS.map((group) => (
            <div key={group.heading} className="space-y-1">
              <div
                className="font-mono-tabular px-3 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em]"
                style={{ color: 'var(--text-muted)' }}
              >
                {group.heading}
              </div>
              {group.items.map((item) => {
                const active = activeTab === item.id
                const Icon =
                  item.id === 'command'
                    ? Activity
                    : item.id === 'onboarding'
                      ? Compass
                      : item.id === 'knowledge'
                        ? BookOpen
                        : item.id === 'life'
                          ? CalendarCheck2
                          : item.id === 'workflows'
                            ? GitBranch
                            : item.id === 'ecosystem'
                              ? Radio
                              : item.id === 'memories'
                                ? Brain
                                : item.id === 'reminders'
                                  ? Bell
                                  : item.id === 'capabilities'
                                    ? Cpu
                                    : item.id === 'storage'
                                      ? HardDrive
                                      : item.id === 'runtime'
                                        ? Layers
                                        : Scale
                return (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={active ? 'page' : undefined}
                    onClick={() => setActiveTab(item.id)}
                    className="group relative flex w-full items-center gap-2.5 rounded-xl border px-3 py-2 text-left text-xs font-medium transition-all hover:bg-[#172840]"
                    style={{
                      borderColor: active ? 'rgba(87, 223, 255, 0.38)' : 'transparent',
                      backgroundColor: active ? 'var(--accent-core-dim)' : 'transparent',
                      color: active ? 'var(--accent-core)' : 'var(--text-secondary)',
                      boxShadow: active ? 'inset 0 1px 0 rgba(214, 240, 255, 0.08)' : 'none',
                    }}
                  >
                    {active && (
                      <span
                        aria-hidden="true"
                        className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r"
                        style={{ backgroundColor: 'var(--accent-core)' }}
                      />
                    )}
                    <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                    <span className="truncate">{item.label}</span>
                  </button>
                )
              })}
            </div>
          ))}
        </nav>

        <main className="min-w-0">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 5 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="space-y-5"
          >
            {activeTab === 'command' && (
              <>
                <div className="grid gap-5 lg:grid-cols-[336px_1fr]">
                  <OrbitalCore
                    machineState={effectiveMachineState}
                    qualityTier={qualityTier}
                    fpsTarget={fpsTarget}
                    detectedRefreshHz={detectedRefreshHz}
                    voiceAmplitude={liveVoice?.amplitude ?? 0}
                    onTelemetryUpdate={updateFrameTelemetry}
                  />

                  <section className="jarvis-panel flex flex-col justify-between rounded-2xl p-6">
                    <div>
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div
                            className="font-mono-tabular text-[10px] font-semibold uppercase tracking-[0.16em]"
                            style={{ color: 'var(--accent-core)' }}
                          >
                            Primary Control Deck
                          </div>
                          <h1 className="font-display mt-1 text-xl font-semibold tracking-tight">
                            J.A.R.V.I.S. — Voice-First Command Center
                          </h1>
                        </div>
                        <span
                          className="font-mono-tabular inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px]"
                          style={{
                            borderColor:
                              liveVoice?.phase === 'listening_command'
                                ? 'rgba(87, 223, 255, 0.5)'
                                : liveVoice?.phase === 'standby_wake'
                                  ? 'rgba(94, 234, 212, 0.5)'
                                  : 'var(--border-subtle)',
                            backgroundColor:
                              liveVoice?.phase === 'listening_command'
                                ? 'var(--accent-core-dim)'
                                : liveVoice?.phase === 'standby_wake'
                                  ? 'var(--status-ok-dim)'
                                  : 'rgba(6, 11, 20, 0.55)',
                            color:
                              liveVoice?.phase === 'listening_command'
                                ? 'var(--accent-core)'
                                : liveVoice?.phase === 'standby_wake'
                                  ? 'var(--status-ok)'
                                  : 'var(--text-secondary)',
                          }}
                        >
                          <span
                            className={
                              isVoiceArmed ? 'jarvis-live-dot h-1.5 w-1.5 rounded-full' : 'h-1.5 w-1.5 rounded-full'
                            }
                            style={{
                              backgroundColor:
                                liveVoice?.phase === 'listening_command'
                                  ? 'var(--accent-core)'
                                  : liveVoice?.phase === 'standby_wake'
                                    ? 'var(--status-ok)'
                                    : 'var(--text-muted)',
                            }}
                          />
                          {liveVoice?.phase === 'listening_command'
                            ? `SESI AKTIF — LANGSUNG BICARA (${liveVoice.session_seconds_left}d)`
                            : liveVoice?.phase === 'standby_wake'
                              ? 'SIAGA — KATAKAN "HEY JARVIS" SEKALI'
                              : liveVoice?.phase === 'transcribing'
                                ? 'MENYIMAK SUARA (WHISPER ID+EN)...'
                                : liveVoice?.phase === 'thinking'
                                  ? 'BERPIKIR (LLM LOKAL)...'
                                  : liveVoice?.phase === 'speaking'
                                    ? 'BERBICARA (PIPER STREAMING)...'
                                    : 'VOICE STANDBY (KLIK AKTIFKAN)'}
                        </span>
                      </div>

                      {/* Primary Voice-First Controls (1 bright primary CTA + quiet secondary controls) */}
                      <div className="mt-5 flex flex-wrap items-center gap-2.5">
                        <button
                          type="button"
                          onClick={() => handleArmVoice('wake')}
                          className="inline-flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-semibold transition-all hover:brightness-110 active:scale-[0.98]"
                          style={{
                            backgroundColor:
                              isVoiceArmed && !liveVoice?.session_active
                                ? 'var(--status-ok)'
                                : 'var(--accent-core)',
                            color: '#060b14',
                            boxShadow: '0 6px 20px rgba(87, 223, 255, 0.24)',
                          }}
                        >
                          <Mic className="h-3.5 w-3.5" aria-hidden="true" />
                          {liveVoice?.session_active
                            ? 'Kembali Siaga ("Hey Jarvis")'
                            : isVoiceArmed
                              ? 'Mode "Hey Jarvis" Siaga'
                              : 'Aktifkan Mode "Hey Jarvis"'}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleArmVoice('active')}
                          className="rounded-xl border px-3.5 py-2.5 text-xs font-medium transition-all hover:bg-[#1c304d] active:scale-[0.98]"
                          style={{
                            borderColor: liveVoice?.session_active ? 'var(--accent-core)' : 'var(--border-strong)',
                            backgroundColor: liveVoice?.session_active
                              ? 'var(--accent-core-dim)'
                              : 'var(--surface-elevated)',
                            color: liveVoice?.session_active ? 'var(--accent-core)' : 'var(--text-primary)',
                          }}
                        >
                          {liveVoice?.session_active ? 'Sesi Ngobrol Aktif' : 'Bangunkan & Ngobrol'}
                        </button>
                        {isVoiceArmed && (
                          <button
                            type="button"
                            onClick={() => handleArmVoice('muted')}
                            className="rounded-xl border px-3.5 py-2.5 text-xs font-medium transition-all hover:bg-[#1c304d] active:scale-[0.98]"
                            style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
                          >
                            Bisukan Mic
                          </button>
                        )}
                        {liveVoice?.phase === 'speaking' && (
                          <button
                            type="button"
                            onClick={() => void stopLiveSpeakingAudio()}
                            className="rounded-xl px-3.5 py-2.5 text-xs font-semibold transition-all hover:brightness-110 active:scale-[0.98]"
                            style={{ backgroundColor: 'var(--status-danger-dim)', color: 'var(--status-danger)' }}
                          >
                            Hentikan Suara
                          </button>
                        )}
                      </div>

                      {/* Conversational Console Readout */}
                      <div className="jarvis-panel-inset mt-5 space-y-2.5 rounded-xl p-4 text-sm">
                        <div className="flex items-center justify-between text-[10px]">
                          <span
                            className="font-mono-tabular uppercase tracking-[0.14em]"
                            style={{ color: 'var(--text-muted)' }}
                          >
                            Live Response Console
                          </span>
                          <span className="font-mono-tabular" style={{ color: 'var(--accent-core)' }}>
                            {effectiveMachineState.toUpperCase()}
                          </span>
                        </div>
                        {liveVoice?.last_transcript && (
                          <div className="rounded-lg px-2.5 py-1.5 text-xs" style={{ backgroundColor: 'rgba(87, 223, 255, 0.06)', color: 'var(--text-secondary)' }}>
                            <span className="font-semibold" style={{ color: 'var(--accent-core)' }}>
                              Anda:
                            </span>{' '}
                            {liveVoice.last_transcript}
                          </div>
                        )}
                        <p className="leading-relaxed" style={{ color: 'var(--text-primary)' }}>
                          {lastTurnReply && lastTurnReplyAt >= liveVoiceReplyMetaRef.current.updatedAt
                            ? lastTurnReply
                            : liveVoice?.last_reply || lastTurnReply || statusAnnouncement}
                        </p>
                        {liveVoice?.error && (
                          <p className="text-xs" style={{ color: 'var(--status-warn)' }}>
                            {liveVoice.error}
                          </p>
                        )}
                        <details className="border-t pt-2.5 text-xs" style={{ borderColor: 'var(--border-subtle)' }}>
                          <summary
                            className="select-none text-[11px] font-medium"
                            style={{ color: 'var(--text-muted)' }}
                          >
                            Detail Teknis Mesin (Wake / VAD / STT / TTS / Brain)
                          </summary>
                          <div
                            className="font-mono-tabular mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-[11px]"
                            style={{ color: 'var(--text-secondary)' }}
                          >
                            <span>
                              Wake:{' '}
                              {liveVoice?.wake_engine === 'openwakeword-hey-jarvis'
                                ? 'openWakeWord (80ms)'
                                : 'Whisper Gate'}
                            </span>
                            <span>VAD: {liveVoice?.vad_engine === 'silero-vad' ? 'Silero Neural' : 'RMS'}</span>
                            <span>STT: {liveVoice?.stt_ready ? `${liveVoice.stt_model} (ID+EN)` : 'Offline/Unloaded'}</span>
                            <span>TTS: {liveVoice?.tts_ready ? 'Piper SSE Streaming' : 'OS Fallback'}</span>
                            <span>
                              Brain:{' '}
                              {liveVoice?.llm_ready
                                ? `${liveVoice.llm_model} (${liveVoice.llm_backend})`
                                : liveVoice?.llm_note ?? 'Direct Mode'}
                            </span>
                          </div>
                        </details>
                      </div>

                      {/* Keyboard Fallback + 1-Click Quick Command Chips */}
                      {showTextForm ? (
                        <div className="mt-4 space-y-2.5">
                          <form onSubmit={handleTurnSubmit} className="flex gap-2">
                            <input
                              type="text"
                              aria-label="Perintah teks lokal"
                              placeholder="Fallback teks (mis: terjemahkan selamat pagi ke bahasa Jepang, atau jam berapa)..."
                              value={turnInput}
                              onChange={(e) => setTurnInput(e.target.value)}
                              className="min-w-0 flex-1 rounded-xl border px-3.5 py-2.5 text-xs transition-colors focus:border-[#57dfff]"
                              style={{
                                backgroundColor: 'rgba(6, 11, 20, 0.8)',
                                borderColor: 'var(--border-strong)',
                              }}
                            />
                            <button
                              type="submit"
                              className="inline-flex items-center gap-1.5 rounded-xl px-4 py-2.5 text-xs font-semibold transition-all hover:brightness-110 active:scale-[0.98]"
                              style={{ backgroundColor: 'var(--accent-core)', color: '#060b14' }}
                            >
                              <Send className="h-3.5 w-3.5" aria-hidden="true" />
                              Kirim
                            </button>
                          </form>
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span
                              className="inline-flex items-center gap-1 text-[11px]"
                              style={{ color: 'var(--text-muted)' }}
                            >
                              <Sparkles className="h-3 w-3" aria-hidden="true" />
                              Coba cepat:
                            </span>
                            {QUICK_COMMANDS.map((cmd) => (
                              <button
                                key={cmd.label}
                                type="button"
                                onClick={() => submitUtterance(cmd.prompt)}
                                className="rounded-full border px-2.5 py-1 text-[11px] transition-all hover:border-[#57dfff] hover:text-[#eaf3ff] active:scale-[0.98]"
                                style={{
                                  borderColor: 'var(--border-subtle)',
                                  backgroundColor: 'rgba(6, 11, 20, 0.55)',
                                  color: 'var(--text-secondary)',
                                }}
                              >
                                {cmd.label}
                              </button>
                            ))}
                          </div>
                        </div>
                      ) : (
                        <div className="mt-4 flex items-center justify-between gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                          <span>
                            {liveVoice?.session_active
                              ? 'Sesi percakapan aktif — langsung bicara bolak-balik tanpa mengulang "Hey Jarvis". Ucapkan "Cukup Jarvis" atau "Tidur dulu" untuk kembali siaga.'
                              : 'Mode siaga aktif — ucapkan "Hey Jarvis" SEKALI untuk membangunkan sesi percakapan berkelanjutan.'}
                          </span>
                          <button
                            type="button"
                            onClick={() => setShowKeyboardFallback(true)}
                            className="shrink-0 rounded-lg border px-2.5 py-1 text-[11px] transition-colors hover:bg-[#1c304d]"
                            style={{ borderColor: 'var(--border-subtle)' }}
                          >
                            Mode Teks (Fallback)
                          </button>
                        </div>
                      )}

                      <div className="jarvis-panel-inset font-mono-tabular mt-4 grid grid-cols-3 divide-x rounded-xl py-3 text-xs" style={{ borderColor: 'var(--border-subtle)' }}>
                        <div className="px-3.5">
                          <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                            Event Cursor
                          </div>
                          <div className="mt-1 text-sm font-semibold">seq #{lastSeq}</div>
                        </div>
                        <div className="px-3.5" style={{ borderColor: 'var(--border-subtle)' }}>
                          <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                            Stale Rejected
                          </div>
                          <div className="mt-1 text-sm font-semibold">{staleEventsRejected}</div>
                        </div>
                        <div className="px-3.5" style={{ borderColor: 'var(--border-subtle)' }}>
                          <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                            Deny-by-Default
                          </div>
                          <div className="mt-1 text-sm font-semibold" style={{ color: 'var(--status-ok)' }}>
                            ENFORCED
                          </div>
                        </div>
                      </div>
                    </div>

                    <div
                      className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t pt-4"
                      style={{ borderColor: 'var(--border-subtle)' }}
                    >
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                        Uji kartu persetujuan R2 berbasis HTML native &lt;dialog&gt;:
                      </span>
                      <button
                        type="button"
                        onClick={triggerSampleR2Preview}
                        className="inline-flex items-center gap-1.5 rounded-xl border px-3.5 py-1.5 text-xs font-medium transition-all hover:brightness-110 active:scale-[0.98]"
                        style={{
                          borderColor: 'rgba(255, 190, 105, 0.45)',
                          color: 'var(--status-warn)',
                          backgroundColor: 'var(--status-warn-dim)',
                        }}
                      >
                        <ShieldAlert className="h-3.5 w-3.5" aria-hidden="true" />
                        Pratinjau Dialog R2
                      </button>
                    </div>
                  </section>
                </div>

                {/* Balanced 3-Column Local Posture & Readiness Deck (fills 1440x900 with real grounded state) */}
                <div className="grid gap-4 md:grid-cols-3">
                  <div className="jarvis-panel rounded-2xl p-4">
                    <div className="flex items-center justify-between">
                      <span
                        className="font-mono-tabular inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em]"
                        style={{ color: 'var(--status-ok)' }}
                      >
                        <ShieldCheck className="h-3.5 w-3.5" aria-hidden="true" />
                        Safety Kernel
                      </span>
                      <span className="font-mono-tabular text-[11px]" style={{ color: 'var(--text-muted)' }}>
                        R1 · R2 · R3
                      </span>
                    </div>
                    <p className="mt-2 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                      Aplikasi aman otomatis (Tier-1), mutasi file wajib diff GUI (Tier-2), dan hapus file pengguna/shell diblokir permanen (Tier-3).
                    </p>
                  </div>

                  <div className="jarvis-panel rounded-2xl p-4">
                    <div className="flex items-center justify-between">
                      <span
                        className="font-mono-tabular inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em]"
                        style={{ color: 'var(--accent-core)' }}
                      >
                        <Cpu className="h-3.5 w-3.5" aria-hidden="true" />
                        Compute &amp; Visuals
                      </span>
                      <button
                        type="button"
                        onClick={() => setActiveTab('capabilities')}
                        className="inline-flex items-center gap-0.5 text-[11px] font-medium transition-colors hover:text-[#eaf3ff]"
                        style={{ color: 'var(--accent-core)' }}
                      >
                        Detail
                        <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
                      </button>
                    </div>
                    <div className="font-mono-tabular mt-2 text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                      {primaryGpu
                        ? `${primaryGpu.name} (${primaryGpu.vram_total_mib} MiB)`
                        : 'Local Adaptive CPU/GPU'}
                    </div>
                    <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                      Tier {qualityTier.toUpperCase()} · {capabilities?.recommendation.support_tier ?? 'Supported'} ·{' '}
                      {Math.round(detectedRefreshHz)} Hz
                    </p>
                  </div>

                  <div className="jarvis-panel rounded-2xl p-4">
                    <div className="flex items-center justify-between">
                      <span
                        className="font-mono-tabular inline-flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em]"
                        style={{ color: 'var(--accent-ice)' }}
                      >
                        <Brain className="h-3.5 w-3.5" aria-hidden="true" />
                        Local State Vault
                      </span>
                      <button
                        type="button"
                        onClick={() => setActiveTab('ecosystem')}
                        className="inline-flex items-center gap-0.5 text-[11px] font-medium transition-colors hover:text-[#eaf3ff]"
                        style={{ color: 'var(--accent-core)' }}
                      >
                        Ekosistem
                        <ArrowUpRight className="h-3 w-3" aria-hidden="true" />
                      </button>
                    </div>
                    <div className="font-mono-tabular mt-2 flex flex-wrap gap-3 text-xs">
                      <span>
                        <strong style={{ color: 'var(--text-primary)' }}>{memories.length}</strong>{' '}
                        <span style={{ color: 'var(--text-muted)' }}>memori</span>
                      </span>
                      <span>
                        <strong style={{ color: 'var(--text-primary)' }}>{reminders.length}</strong>{' '}
                        <span style={{ color: 'var(--text-muted)' }}>pengingat</span>
                      </span>
                      <span>
                        <strong style={{ color: 'var(--text-primary)' }}>{haEntities.length}</strong>{' '}
                        <span style={{ color: 'var(--text-muted)' }}>IoT</span>
                      </span>
                    </div>
                    <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                      {privacy.offlineMode
                        ? 'Air-gapped lokal — nol trafik jaringan keluar.'
                        : 'Jaringan opsional terbuka dengan guard anti-SSRF.'}
                    </p>
                  </div>
                </div>
              </>
            )}

          {activeTab === 'onboarding' && (
            <OnboardingWizard
              capabilities={capabilities}
              storageLocations={storageLocations}
              qualityTier={qualityTier}
              fpsTarget={fpsTarget}
              runtimeOwnershipMode={runtimeOwnershipMode}
              onApplyRecommendedSetup={() => {
                if (capabilities) {
                  setQualityTier(capabilities.recommendation.recommended_visual_tier)
                  setFpsTarget(capabilities.recommendation.recommended_fps_target)
                  setRuntimeOwnershipMode(capabilities.recommendation.recommended_runtime_ownership)
                }
              }}
              onSelectRuntime={setRuntimeOwnershipMode}
              onSelectVisuals={(tier, fps) => {
                setQualityTier(tier)
                setFpsTarget(fps)
              }}
              onCompleteOnboarding={({ timezoneIana: tz, grantedCapabilities }) => {
                completeOnboarding(tz)
                void persistOnboardingCompletion(grantedCapabilities)
              }}
            />
          )}

          {activeTab === 'knowledge' && (
            <KnowledgePanel
              roots={knowledgeRoots}
              onAddRoot={(path) => {
                const tempId = `root-${Date.now()}`
                if (brokerSource === 'tauri_broker') {
                  useJarvisStore.setState((s) => ({
                    knowledgeRoots: [
                      ...s.knowledgeRoots,
                      { id: tempId, canonical_path: path, enabled: true, revision: 1 },
                    ],
                  }))
                  void persistKnowledgeRootAdd(path).then((persisted) => {
                    if (persisted) replaceKnowledgeRootId(tempId, persisted)
                  })
                } else {
                  addKnowledgeRoot(path)
                }
              }}
              onRevokeRoot={(id) => {
                revokeKnowledgeRoot(id)
                void persistKnowledgeRootRevoke(id)
              }}
              onSearchKnowledge={brokerSource === 'tauri_broker' ? queryKnowledgeLive : undefined}
            />
          )}

          {activeTab === 'life' && (
            <PersonalLifePanel
              tasks={tasks}
              expenseSummaries={expenseSummaries}
              onCreateTask={(title) => {
                addTask(title)
                void persistTaskCreate(title)
              }}
              onToggleTaskDone={toggleTaskDone}
              onRecordExpense={({ amountMinor, currencyIso, kind, category }) => {
                recordExpense({ amountMinor, currencyIso, kind })
                void persistExpenseRecord({ amountMinor, currencyIso, kind, category })
              }}
            />
          )}

          {activeTab === 'workflows' && (
            <WorkflowsPanel workflows={workflows} onCreateSampleWorkflow={addWorkflow} />
          )}

          {activeTab === 'ecosystem' && (
            <EcosystemPanel
              cameraActive={privacy.cameraActive}
              haEntities={haEntities}
              remoteGatewayEnabled={remoteGatewayEnabled}
              remoteHostAvailable={remoteHostAvailable}
              remoteDevices={remoteDevices}
              preferenceProposals={preferenceProposals}
              activePersonaVerbosity={activePersonaVerbosity}
              offlineMode={privacy.offlineMode}
              onSetCameraActive={setCameraActive}
              onAddHaEntity={(entityId, friendlyName) => {
                const ok = addHaEntity(entityId, friendlyName)
                if (ok) void persistHaEntityAdd(entityId, friendlyName)
                return ok
              }}
              onToggleRemoteGateway={toggleRemoteGateway}
              onToggleRemoteHostAvailable={toggleRemoteHostAvailable}
              onRevokeRemoteDevice={(deviceId) => {
                revokeRemoteDevice(deviceId)
                void persistRemoteDeviceRevoke(deviceId)
              }}
              onDecideProposal={(id, decision) => {
                decidePreferenceProposal(id, decision)
                void persistPreferenceDecision(id, decision)
              }}
            />
          )}

          {activeTab === 'memories' && (
            <MemoryVaultPanel
              memories={memories}
              onCreateMemory={({ kind, content, sensitivity }) => {
                const tempId = `mem-${Date.now()}`
                addMemory({
                  id: tempId,
                  kind,
                  content,
                  is_encrypted: sensitivity === 'sensitive',
                  sensitivity,
                  source_ref: 'local_owner',
                  status: 'active',
                  revision: 1,
                  created_at: new Date().toISOString(),
                  updated_at: new Date().toISOString(),
                })
                void persistMemoryCreate({ kind, content, sensitivity }).then((persisted) => {
                  if (persisted) replaceMemoryId(tempId, persisted)
                })
              }}
              onApproveProposal={(id) => approveMemoryProposal(id)}
              onDeleteMemory={(id) => {
                removeMemory(id)
                void persistMemoryDelete(id)
              }}
            />
          )}

          {activeTab === 'reminders' && (
            <RemindersPanel
              reminders={reminders}
              defaultTimezone={timezoneIana}
              onCreateReminder={({ title, minutesFromNow, timezoneIana: tz }) => {
                const dueAtUtc = new Date(Date.now() + minutesFromNow * 60_000).toISOString()
                addReminder({
                  id: `rem-${Date.now()}`,
                  title,
                  due_at_utc: dueAtUtc,
                  timezone_iana: tz,
                  state: 'scheduled',
                  revision: 1,
                })
                void persistReminderCreate({ title, dueAtUtc, timezoneIana: tz })
              }}
              onDismissReminder={(id) => dismissReminder(id)}
            />
          )}

          {activeTab === 'capabilities' && (
            <CapabilitiesPanel
              data={capabilities}
              onApplyRecommended={(tier, fps, ownership) => {
                setQualityTier(tier)
                setFpsTarget(fps)
                setRuntimeOwnershipMode(ownership)
              }}
            />
          )}

          {activeTab === 'storage' && <StorageManagerPanel locations={storageLocations} />}

          {activeTab === 'runtime' && (
            <RuntimeVisualPanel
              ownershipMode={runtimeOwnershipMode}
              qualityTier={qualityTier}
              fpsTarget={fpsTarget}
              detectedRefreshHz={detectedRefreshHz}
              telemetry={frameTelemetry}
              voiceDiagnostics={voiceDiagnostics}
              onOwnershipChange={setRuntimeOwnershipMode}
              onQualityChange={setQualityTier}
              onFpsChange={setFpsTarget}
              onSelectAudioDevices={(inputDeviceId, outputDeviceId) => {
                void selectBrokerAudioDevices({ inputDeviceId, outputDeviceId }).then(() =>
                  fetchVoiceDiagnostics().then((vd) => {
                    if (vd) setVoiceDiagnostics(vd)
                  }),
                )
              }}
              onSpeechRateChange={(rate) => {
                void setBrokerSpeechRate(rate).then(() =>
                  fetchVoiceDiagnostics().then((vd) => {
                    if (vd) setVoiceDiagnostics(vd)
                  }),
                )
              }}
              onReplayTranscript={(transcript) => {
                void replayVoiceTranscript(transcript).then((res) => {
                  if (!res) return
                  setLastTurnReply(res.reply, res.approval ? 'Approval' : 'Success')
                  if (res.approval) openApprovalChallenge(res.approval)
                })
              }}
            />
          )}

          {activeTab === 'licenses' && <LicenseInventoryPanel artifacts={licenses} />}
          </motion.div>
        </main>
      </div>

      <ApprovalDialog
        challenge={pendingApproval}
        onApprove={handleApprove}
        onReject={handleReject}
        onExpire={handleExpire}
      />
    </div>
  )
}

export default App
