import { useState } from 'react'
import { Camera, Home, Radio, ShieldBan, SlidersHorizontal, Smartphone, Square } from 'lucide-react'
import type {
  HaEntityItem,
  PreferenceProposalItem,
  RemoteDeviceItem,
} from '../lib/contracts'

interface EcosystemPanelProps {
  readonly cameraActive: boolean
  readonly haEntities: ReadonlyArray<HaEntityItem>
  readonly remoteGatewayEnabled: boolean
  readonly remoteHostAvailable: boolean
  readonly remoteDevices: ReadonlyArray<RemoteDeviceItem>
  readonly preferenceProposals: ReadonlyArray<PreferenceProposalItem>
  readonly activePersonaVerbosity: 'brief' | 'standard' | 'detailed'
  readonly onSetCameraActive: (active: boolean) => void
  readonly onAddHaEntity: (entityId: string, friendlyName: string) => boolean
  readonly onToggleRemoteGateway: () => void
  readonly onToggleRemoteHostAvailable: () => void
  readonly onRevokeRemoteDevice: (deviceId: string) => void
  readonly onDecideProposal: (id: string, decision: 'approve' | 'reject') => void
}

export function EcosystemPanel({
  cameraActive,
  haEntities,
  remoteGatewayEnabled,
  remoteHostAvailable,
  remoteDevices,
  preferenceProposals,
  activePersonaVerbosity,
  onSetCameraActive,
  onAddHaEntity,
  onToggleRemoteGateway,
  onToggleRemoteHostAvailable,
  onRevokeRemoteDevice,
  onDecideProposal,
}: EcosystemPanelProps) {
  const [entityId, setEntityId] = useState('')
  const [friendlyName, setFriendlyName] = useState('')
  const [haFeedback, setHaFeedback] = useState<string | null>(null)

  const handleAddHa = (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!entityId.trim()) return
    const ok = onAddHaEntity(entityId.trim(), friendlyName.trim())
    if (ok) {
      setHaFeedback(`Entitas '${entityId.trim()}' lolos filter R3 dan masuk allowlist.`)
      setEntityId('')
      setFriendlyName('')
    } else {
      setHaFeedback(`Ditolak (R3): '${entityId.trim()}' termasuk perangkat keselamatan / format tidak valid.`)
    }
  }

  return (
    <div className="space-y-5">
      {/* B17: On-Demand Camera Understanding */}
      <section
        className="rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Camera className="h-4 w-4" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
            <h2 className="text-base font-semibold">Kamera On-Demand (FR-IOT-01)</h2>
          </div>
          <span
            className="font-mono-tabular rounded-md border px-2 py-0.5 text-xs"
            style={{
              borderColor: cameraActive ? 'var(--status-warn)' : 'var(--border-subtle)',
              color: cameraActive ? 'var(--status-warn)' : 'var(--text-muted)',
            }}
          >
            {cameraActive ? 'INDICATOR: ACTIVE (RAM-ONLY)' : 'INDICATOR: OFF · NO BACKGROUND CAPTURE'}
          </span>
        </div>
        <p className="mt-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
          Izin eksplisit per sesi, tanpa pengenalan wajah, dan frame mentah dihapus dari RAM segera setelah selesai atau sesi OS terkunci.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onSetCameraActive(true)}
            disabled={cameraActive}
            className="rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-[#1c2c44] active:scale-[0.99] disabled:opacity-50"
            style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
          >
            Izinkan Snapshot Sesi Ini
          </button>
          <button
            type="button"
            onClick={() => onSetCameraActive(false)}
            disabled={!cameraActive}
            className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99] disabled:opacity-50"
            style={{ backgroundColor: 'var(--status-danger-dim)', color: 'var(--status-danger)' }}
          >
            <Square className="h-3 w-3" aria-hidden="true" />
            Hentikan Kamera Segera
          </button>
        </div>
      </section>

      {/* B18: Home Assistant Allowlist & R3 Safety-Actuation Hard Ban */}
      <section
        className="rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Home className="h-4 w-4" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
            <h2 className="text-base font-semibold">Home Assistant Allowlist (FR-IOT-02..04)</h2>
          </div>
          <span
            className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs font-medium"
            style={{ backgroundColor: 'var(--status-danger-dim)', color: 'var(--status-danger)' }}
          >
            <ShieldBan className="h-3.5 w-3.5" aria-hidden="true" />
            R3 Ban: Lock · Alarm · Heater · Gas · Garage
          </span>
        </div>

        <form onSubmit={handleAddHa} className="mt-3 flex flex-wrap gap-2">
          <input
            type="text"
            aria-label="Entity ID Home Assistant"
            placeholder="Contoh aman: light.living_room (lock.* ditolak)"
            value={entityId}
            onChange={(e) => setEntityId(e.target.value)}
            className="min-w-[220px] flex-1 rounded-lg border px-3 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <input
            type="text"
            aria-label="Nama ramah entitas"
            placeholder="Nama perangkat"
            value={friendlyName}
            onChange={(e) => setFriendlyName(e.target.value)}
            className="min-w-[160px] rounded-lg border px-3 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <button
            type="submit"
            className="rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
            style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
          >
            Tambah Allowlist
          </button>
        </form>

        {haFeedback && (
          <p className="mt-2 text-xs" style={{ color: 'var(--status-warn)' }}>
            {haFeedback}
          </p>
        )}

        <ul className="mt-3 space-y-2">
          {haEntities.map((ent) => (
            <li
              key={ent.entity_id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs"
              style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-subtle)' }}
            >
              <div>
                <span className="font-semibold">{ent.friendly_name}</span>{' '}
                <span className="font-mono-tabular" style={{ color: 'var(--text-muted)' }}>
                  ({ent.entity_id})
                </span>
              </div>
              <span className="font-mono-tabular" style={{ color: 'var(--status-ok)' }}>
                {ent.allowed_actions.join(', ')}
              </span>
            </li>
          ))}
        </ul>
      </section>

      {/* B19: Separate Private Scoped Remote Mobile Gateway */}
      <section
        className="rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Smartphone className="h-4 w-4" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
            <h2 className="text-base font-semibold">Private Scoped Remote Gateway (FR-REM-01/02/04)</h2>
          </div>
          <span
            data-testid="remote-host-badge"
            className="font-mono-tabular inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs"
            style={{
              borderColor: !remoteHostAvailable
                ? 'var(--status-danger)'
                : remoteGatewayEnabled
                  ? 'var(--status-ok)'
                  : 'var(--border-subtle)',
              color: !remoteHostAvailable
                ? 'var(--status-danger)'
                : remoteGatewayEnabled
                  ? 'var(--status-ok)'
                  : 'var(--text-muted)',
            }}
          >
            <Radio className="h-3 w-3" aria-hidden="true" />
            {!remoteHostAvailable
              ? 'HOST UNREACHABLE (NO SILENT QUEUE)'
              : remoteGatewayEnabled
                ? 'ENABLED · PRIVATE VPN/TLS ONLY'
                : 'DISABLED BY DEFAULT'}
          </span>
        </div>

        <p className="mt-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
          Pendengar terpisah tanpa port publik (tolak 0.0.0.0). Cakupan mobile terbatas pada status, chat berizin, &amp; pengingat — dilarang menjalankan R2, file, kamera, atau perubahan izin.
        </p>

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onToggleRemoteGateway}
            className="rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
            style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
          >
            {remoteGatewayEnabled ? 'Nonaktifkan Gateway' : 'Aktifkan Gateway Privat'}
          </button>
          <button
            type="button"
            onClick={onToggleRemoteHostAvailable}
            className="rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
            style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
          >
            {remoteHostAvailable ? 'Simulasikan Host Tidur/Offline' : 'Pulihkan Ketersediaan Host'}
          </button>
        </div>

        <ul className="mt-3 space-y-2">
          {remoteDevices.map((dev) => (
            <li
              key={dev.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs"
              style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-subtle)' }}
            >
              <div>
                <div className="font-semibold">{dev.label}</div>
                <div className="font-mono-tabular mt-0.5" style={{ color: 'var(--text-muted)' }}>
                  Scopes: {dev.scopes.join(', ')}
                </div>
              </div>
              {dev.revoked_at ? (
                <span className="font-mono-tabular" style={{ color: 'var(--status-danger)' }}>
                  REVOKED
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => onRevokeRemoteDevice(dev.id)}
                  className="rounded-md px-2.5 py-1 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
                  style={{ backgroundColor: 'var(--status-danger-dim)', color: 'var(--status-danger)' }}
                >
                  Cabut Seketika
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      {/* B20: Adaptive Preference Proposals */}
      <section
        className="rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="h-4 w-4" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
            <h2 className="text-base font-semibold">Proposal Preferensi Adaptif (FR-REM-03)</h2>
          </div>
          <span
            data-testid="active-verbosity-badge"
            className="font-mono-tabular rounded-md border px-2 py-0.5 text-xs"
            style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-secondary)' }}
          >
            Aktif: persona.verbosity = {activePersonaVerbosity}
          </span>
        </div>

        <p className="mt-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
          Menolak atau mengabaikan proposal tidak mengubah konfigurasi aktif; eskalasi kebijakan keamanan/izin dilarang keras.
        </p>

        <ul className="mt-3 space-y-2">
          {preferenceProposals.map((prop) => (
            <li
              key={prop.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2.5 text-xs"
              style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-subtle)' }}
            >
              <div>
                <div className="font-semibold">
                  {prop.preference_key} &rarr; <span className="font-mono-tabular">{prop.proposed_value}</span>
                </div>
                <div className="mt-0.5" style={{ color: 'var(--text-muted)' }}>
                  {prop.rationale} (bukti: {prop.evidence_count}x)
                </div>
              </div>
              {prop.status === 'pending' ? (
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => onDecideProposal(prop.id, 'reject')}
                    className="rounded-md border px-2.5 py-1 text-xs font-medium transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
                    style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
                  >
                    Tolak
                  </button>
                  <button
                    type="button"
                    onClick={() => onDecideProposal(prop.id, 'approve')}
                    className="rounded-md px-2.5 py-1 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
                    style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
                  >
                    Setujui Lokal
                  </button>
                </div>
              ) : (
                <span className="font-mono-tabular uppercase" style={{ color: 'var(--text-muted)' }}>
                  {prop.status}
                </span>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
