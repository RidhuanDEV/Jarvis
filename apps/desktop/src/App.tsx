import { useCallback, useEffect, useState } from 'react'
import {
  Activity,
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
  Scale,
  Send,
  ShieldAlert,
  Square,
  Wifi,
  WifiOff,
} from 'lucide-react'
import { ApprovalDialog } from './components/ApprovalDialog'
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
  dispatchApprovalDecision,
  dispatchCommandTurn,
  loadFoundationData,
} from './lib/brokerClient'
import type { ApprovalChallenge } from './lib/contracts'
import { useJarvisStore, type NavigationTab } from './store/jarvisStore'

const NAV_ITEMS: ReadonlyArray<{ readonly id: NavigationTab; readonly label: string }> = [
  { id: 'command', label: 'Command Center' },
  { id: 'onboarding', label: 'Onboarding (10 Steps)' },
  { id: 'knowledge', label: 'Knowledge (Hybrid RAG)' },
  { id: 'life', label: 'Personal Life' },
  { id: 'workflows', label: 'Workflows' },
  { id: 'memories', label: 'Memory Vault' },
  { id: 'reminders', label: 'Reminders' },
  { id: 'capabilities', label: 'Hardware Discovery' },
  { id: 'storage', label: 'Storage (11 Roots)' },
  { id: 'runtime', label: 'Runtime & Visuals' },
  { id: 'licenses', label: 'Licenses & SBOM' },
]

export function App() {
  const {
    activeTab,
    machineState,
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
    timezoneIana,
    lastTurnReply,
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
    setCapabilities,
    setStorageLocations,
    setLicenses,
    addMemory,
    approveMemoryProposal,
    removeMemory,
    addReminder,
    dismissReminder,
    addKnowledgeRoot,
    revokeKnowledgeRoot,
    addTask,
    toggleTaskDone,
    recordExpense,
    addWorkflow,
    completeOnboarding,
    setLastTurnReply,
    updateFrameTelemetry,
  } = useJarvisStore()

  const [turnInput, setTurnInput] = useState('')

  useEffect(() => {
    let active = true
    void loadFoundationData().then((data) => {
      if (!active) return
      setCapabilities(data.capabilities)
      setStorageLocations(data.storageLocations)
      setLicenses(data.licenses)
    })
    return () => {
      active = false
    }
  }, [setCapabilities, setStorageLocations, setLicenses])

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

  const handleTurnSubmit = (ev: React.FormEvent) => {
    ev.preventDefault()
    const trimmed = turnInput.trim()
    if (!trimmed) return
    setTurnInput('')
    void dispatchCommandTurn(trimmed).then((res) => {
      setLastTurnReply(res.reply, res.approval ? 'Approval' : 'Success')
      if (res.approval) {
        openApprovalChallenge(res.approval)
      }
    })
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

  return (
    <div className="flex min-h-screen flex-col">
      {/* Screen-reader polite state announcements (10-UX-DESIGN.md §6) */}
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {statusAnnouncement}
      </div>

      {/* Explicit privacy & execution boundary header */}
      <header
        className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-3">
          <span
            className="font-mono-tabular text-sm font-bold tracking-widest"
            style={{ color: 'var(--accent-core)' }}
          >
            J.A.R.V.I.S.
          </span>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            Personal Intelligence OS · v0.2.1
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span
            data-testid="badge-mic"
            className="font-mono-tabular inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1"
            style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-secondary)' }}
          >
            {privacy.micMode === 'muted' ? (
              <MicOff className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <Mic className="h-3.5 w-3.5" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
            )}
            MIC: {privacy.micMode.toUpperCase()}
          </span>

          <span
            data-testid="badge-cam"
            className="font-mono-tabular inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1"
            style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-secondary)' }}
          >
            CAM: OFF
          </span>

          <span
            data-testid="badge-network"
            className="font-mono-tabular inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1"
            style={{
              borderColor: privacy.offlineMode ? 'var(--status-ok)' : 'var(--status-warn)',
              color: privacy.offlineMode ? 'var(--status-ok)' : 'var(--status-warn)',
            }}
          >
            {privacy.offlineMode ? (
              <WifiOff className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <Wifi className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {privacy.offlineMode ? 'OFFLINE' : 'LOCAL + OPTIONAL NET'}
          </span>

          <span
            className="font-mono-tabular rounded-md border px-2.5 py-1"
            style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-secondary)' }}
          >
            ZONE: {privacy.executionZone.toUpperCase()}
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={toggleMute}
            className="rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-[#1c2c44]"
            style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
          >
            {privacy.micMode === 'muted' ? 'Aktifkan PTT' : 'Bisukan Mic'}
          </button>
          <button
            type="button"
            onClick={toggleOfflineMode}
            className="rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors hover:bg-[#1c2c44]"
            style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
          >
            {privacy.offlineMode ? 'Buka Jaringan Opsional' : 'Aktifkan Offline'}
          </button>
          <button
            type="button"
            onClick={cancelActiveRequest}
            className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors hover:brightness-110"
            style={{ backgroundColor: 'var(--status-danger-dim)', color: 'var(--status-danger)' }}
          >
            <Square className="h-3 w-3" aria-hidden="true" />
            Stop
          </button>
        </div>
      </header>

      <div className="mx-auto grid w-full max-w-6xl flex-1 gap-6 p-5 md:grid-cols-[220px_1fr]">
        <nav aria-label="Navigasi utama" className="space-y-1.5">
          {NAV_ITEMS.map((item) => {
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
                className="flex w-full items-center gap-2.5 rounded-lg border px-3 py-2.5 text-left text-xs font-medium transition-colors hover:bg-[#1c2c44]"
                style={{
                  borderColor: active ? 'var(--accent-core)' : 'transparent',
                  backgroundColor: active ? 'var(--accent-core-dim)' : 'transparent',
                  color: active ? 'var(--accent-core)' : 'var(--text-secondary)',
                }}
              >
                <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                {item.label}
              </button>
            )
          })}
        </nav>

        <main className="min-w-0 space-y-5">
          {activeTab === 'command' && (
            <div className="grid gap-5 lg:grid-cols-[280px_1fr]">
              <OrbitalCore
                machineState={machineState}
                qualityTier={qualityTier}
                fpsTarget={fpsTarget}
                detectedRefreshHz={detectedRefreshHz}
                onTelemetryUpdate={updateFrameTelemetry}
              />

              <section
                className="flex flex-col justify-between rounded-xl border p-5"
                style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
              >
                <div>
                  <h1 className="text-lg font-semibold">Command Center — Deterministic-First OS</h1>
                  <p className="mt-1.5 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                    {lastTurnReply || statusAnnouncement}
                  </p>

                  <form onSubmit={handleTurnSubmit} className="mt-4 flex gap-2">
                    <input
                      type="text"
                      aria-label="Perintah teks lokal"
                      placeholder="Contoh: jam berapa, atur volume ke 40, pindahkan file a.txt ke b.txt..."
                      value={turnInput}
                      onChange={(e) => setTurnInput(e.target.value)}
                      className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-xs"
                      style={{
                        backgroundColor: 'var(--surface-canvas)',
                        borderColor: 'var(--border-strong)',
                      }}
                    />
                    <button
                      type="submit"
                      className="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
                      style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
                    >
                      <Send className="h-3.5 w-3.5" aria-hidden="true" />
                      Kirim
                    </button>
                  </form>

                  <div
                    className="font-mono-tabular mt-4 grid grid-cols-3 gap-3 rounded-lg border p-3 text-xs"
                    style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-subtle)' }}
                  >
                    <div>
                      <div style={{ color: 'var(--text-muted)' }}>Event Cursor</div>
                      <div className="mt-0.5 text-sm font-semibold">seq #{lastSeq}</div>
                    </div>
                    <div>
                      <div style={{ color: 'var(--text-muted)' }}>Stale Rejected</div>
                      <div className="mt-0.5 text-sm font-semibold">{staleEventsRejected}</div>
                    </div>
                    <div>
                      <div style={{ color: 'var(--text-muted)' }}>Deny-by-Default</div>
                      <div className="mt-0.5 text-sm font-semibold" style={{ color: 'var(--status-ok)' }}>
                        ENFORCED
                      </div>
                    </div>
                  </div>
                </div>

                <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t pt-4" style={{ borderColor: 'var(--border-subtle)' }}>
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    Uji kartu persetujuan R2 berbasis HTML native &lt;dialog&gt;:
                  </span>
                  <button
                    type="button"
                    onClick={triggerSampleR2Preview}
                    className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-[#1c2c44]"
                    style={{
                      borderColor: 'var(--status-warn)',
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
              onCompleteOnboarding={({ timezoneIana: tz }) => completeOnboarding(tz)}
            />
          )}

          {activeTab === 'knowledge' && (
            <KnowledgePanel
              roots={knowledgeRoots}
              onAddRoot={addKnowledgeRoot}
              onRevokeRoot={revokeKnowledgeRoot}
            />
          )}

          {activeTab === 'life' && (
            <PersonalLifePanel
              tasks={tasks}
              expenseSummaries={expenseSummaries}
              onCreateTask={addTask}
              onToggleTaskDone={toggleTaskDone}
              onRecordExpense={({ amountMinor, currencyIso, kind }) =>
                recordExpense({ amountMinor, currencyIso, kind })
              }
            />
          )}

          {activeTab === 'workflows' && (
            <WorkflowsPanel workflows={workflows} onCreateSampleWorkflow={addWorkflow} />
          )}

          {activeTab === 'memories' && (
            <MemoryVaultPanel
              memories={memories}
              onCreateMemory={({ kind, content, sensitivity }) =>
                addMemory({
                  id: `mem-${Date.now()}`,
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
              }
              onApproveProposal={(id) => approveMemoryProposal(id)}
              onDeleteMemory={(id) => removeMemory(id)}
            />
          )}

          {activeTab === 'reminders' && (
            <RemindersPanel
              reminders={reminders}
              defaultTimezone={timezoneIana}
              onCreateReminder={({ title, minutesFromNow, timezoneIana: tz }) =>
                addReminder({
                  id: `rem-${Date.now()}`,
                  title,
                  due_at_utc: new Date(Date.now() + minutesFromNow * 60_000).toISOString(),
                  timezone_iana: tz,
                  state: 'scheduled',
                  revision: 1,
                })
              }
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
              onOwnershipChange={setRuntimeOwnershipMode}
              onQualityChange={setQualityTier}
              onFpsChange={setFpsTarget}
            />
          )}

          {activeTab === 'licenses' && <LicenseInventoryPanel artifacts={licenses} />}
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
