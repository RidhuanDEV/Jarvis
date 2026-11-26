import { useState } from 'react'
import { Cpu, HardDrive, Layers, Scale, ShieldCheck } from 'lucide-react'
import type {
  FpsTarget,
  HardwareCapabilitiesResponse,
  LicenseArtifact,
  RuntimeOwnershipMode,
  StorageLocation,
  SupportTier,
  VisualQualityTier,
} from '../lib/contracts'
import type { FrameTelemetrySnapshot } from '../lib/visualEngine'

const SUPPORT_BADGE_STYLE: Readonly<Record<SupportTier, { bg: string; fg: string }>> = {
  Supported: { bg: 'rgba(94, 234, 212, 0.14)', fg: '#5eead4' },
  Experimental: { bg: 'rgba(255, 190, 105, 0.14)', fg: '#ffbe69' },
  Unverified: { bg: 'rgba(169, 185, 204, 0.16)', fg: '#a9b9cc' },
  Unsupported: { bg: 'rgba(255, 115, 124, 0.16)', fg: '#ff737c' },
}

export function CapabilitiesPanel({
  data,
  onApplyRecommended,
}: {
  readonly data: HardwareCapabilitiesResponse | null
  readonly onApplyRecommended: (tier: VisualQualityTier, fps: FpsTarget, ownership: RuntimeOwnershipMode) => void
}) {
  if (!data) {
    return (
      <section className="rounded-xl border p-6" style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}>
        <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
          Memuat deteksi kapabilitas perangkat keras…
        </p>
      </section>
    )
  }

  const { snapshot, recommendation } = data
  const badge = SUPPORT_BADGE_STYLE[recommendation.support_tier]
  const ramGib = (snapshot.ram_total_bytes / (1024 ** 3)).toFixed(1)

  return (
    <section className="space-y-4">
      <div
        className="flex flex-wrap items-center justify-between gap-4 rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-3">
          <Cpu className="h-5 w-5" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <div>
            <h2 className="text-base font-semibold">Hardware Capability Discovery & Recommended Setup</h2>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Konvensi adaptif otomatis dengan override penuh — tanpa mengunci spesifikasi satu perangkat.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span
            className="font-mono-tabular rounded-md px-2.5 py-1 text-xs font-semibold"
            style={{ backgroundColor: badge.bg, color: badge.fg }}
          >
            {recommendation.support_tier}
          </span>
          <button
            type="button"
            onClick={() =>
              onApplyRecommended(
                recommendation.recommended_visual_tier,
                recommendation.recommended_fps_target,
                recommendation.recommended_runtime_ownership,
              )
            }
            className="rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
            style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
          >
            Terapkan Recommended Setup
          </button>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl border p-4" style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}>
          <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
            Perangkat Terdeteksi
          </h3>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between gap-4">
              <dt style={{ color: 'var(--text-secondary)' }}>Sistem Operasi</dt>
              <dd className="font-mono-tabular">{snapshot.os_info.system} ({snapshot.os_info.arch})</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: 'var(--text-secondary)' }}>CPU Cores</dt>
              <dd className="font-mono-tabular">
                {snapshot.cpu.physical_cores}P / {snapshot.cpu.logical_cores}T
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: 'var(--text-secondary)' }}>Total RAM</dt>
              <dd className="font-mono-tabular">{ramGib} GiB</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: 'var(--text-secondary)' }}>GPU Terdeteksi</dt>
              <dd className="font-mono-tabular text-right">
                {snapshot.gpus.length === 0
                  ? 'CPU-Only'
                  : snapshot.gpus.map((g) => `${g.name} (${g.vram_total_mib} MiB)`).join(', ')}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: 'var(--text-secondary)' }}>Layar Utama</dt>
              <dd className="font-mono-tabular">
                {snapshot.displays[0]
                  ? `${snapshot.displays[0].width_px}×${snapshot.displays[0].height_px} @ ${snapshot.displays[0].refresh_hz} Hz`
                  : 'Default'}
              </dd>
            </div>
          </dl>
        </div>

        <div className="rounded-xl border p-4" style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}>
          <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
            Profil Rekomendasi
          </h3>
          <dl className="mt-3 space-y-2 text-sm">
            <div className="flex justify-between gap-4">
              <dt style={{ color: 'var(--text-secondary)' }}>Mode AI / Backend</dt>
              <dd className="font-mono-tabular">
                {recommendation.recommended_ai_mode} / {recommendation.recommended_backend.toUpperCase()}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: 'var(--text-secondary)' }}>Kelas Model</dt>
              <dd className="font-mono-tabular text-right">{recommendation.recommended_model_class}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: 'var(--text-secondary)' }}>Batas RAM / VRAM</dt>
              <dd className="font-mono-tabular">
                {recommendation.recommended_max_ram_mib} MiB / {recommendation.recommended_max_vram_mib} MiB
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt style={{ color: 'var(--text-secondary)' }}>Visual / FPS</dt>
              <dd className="font-mono-tabular">
                {recommendation.recommended_visual_tier} / {recommendation.recommended_fps_target}
              </dd>
            </div>
          </dl>
          <ul className="mt-3 space-y-1 border-t pt-3 text-xs" style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-secondary)' }}>
            {recommendation.reasons.map((r) => (
              <li key={r}>• {r}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  )
}

export function StorageManagerPanel({
  locations,
}: {
  readonly locations: ReadonlyArray<StorageLocation>
}) {
  const [cacheQuotaPreset, setCacheQuotaPreset] = useState<'10 GB' | '25 GB' | '50 GB' | 'Unlimited'>('10 GB')

  return (
    <section className="space-y-4">
      <div
        className="flex flex-wrap items-center justify-between gap-4 rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-3">
          <HardDrive className="h-5 w-5" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <div>
            <h2 className="text-base font-semibold">11-Root Dynamic Storage Manager</h2>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Database SQLite WAL (core_db, knowledge_db) wajib pada filesystem lokal. Pembersihan cache tidak pernah menghapus data pengguna (BR-SYS-02).
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1.5" role="group" aria-label="Batas kuota cache maksimum">
          {(['10 GB', '25 GB', '50 GB', 'Unlimited'] as const).map((preset) => {
            const active = cacheQuotaPreset === preset
            return (
              <button
                key={preset}
                type="button"
                onClick={() => setCacheQuotaPreset(preset)}
                className="font-mono-tabular rounded-md border px-2.5 py-1 text-xs font-medium transition-colors hover:bg-[#1c2c44]"
                style={{
                  borderColor: active ? 'var(--accent-core)' : 'var(--border-subtle)',
                  backgroundColor: active ? 'var(--accent-core-dim)' : 'var(--surface-elevated)',
                  color: active ? 'var(--accent-core)' : 'var(--text-secondary)',
                }}
              >
                {preset}
              </button>
            )
          })}
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border" style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}>
        <table className="w-full text-left text-xs">
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border-subtle)', color: 'var(--text-muted)' }}>
              <th className="px-4 py-3 font-semibold">Kategori</th>
              <th className="px-4 py-3 font-semibold">Jalur Konfigurasi</th>
              <th className="px-4 py-3 font-semibold">Filesystem</th>
              <th className="px-4 py-3 font-semibold">Status</th>
            </tr>
          </thead>
          <tbody>
            {locations.map((loc) => {
              const isWal = loc.category === 'core_db' || loc.category === 'knowledge_db'
              return (
                <tr key={loc.category} style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                  <td className="font-mono-tabular px-4 py-2.5 font-medium">
                    {loc.category}
                    {isWal && (
                      <span
                        className="ml-2 rounded px-1.5 py-0.5 text-[10px]"
                        style={{ backgroundColor: 'var(--accent-core-dim)', color: 'var(--accent-core)' }}
                      >
                        WAL LOCAL ONLY
                      </span>
                    )}
                  </td>
                  <td className="font-mono-tabular px-4 py-2.5" style={{ color: 'var(--text-secondary)' }}>
                    {loc.resolved_path}
                  </td>
                  <td className="font-mono-tabular px-4 py-2.5">{loc.filesystem_kind}</td>
                  <td className="font-mono-tabular px-4 py-2.5">
                    <span
                      style={{
                        color: loc.status === 'healthy' ? 'var(--status-ok)' : 'var(--status-danger)',
                      }}
                    >
                      {loc.status.toUpperCase()}
                    </span>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

export function RuntimeVisualPanel({
  ownershipMode,
  qualityTier,
  fpsTarget,
  detectedRefreshHz,
  telemetry,
  onOwnershipChange,
  onQualityChange,
  onFpsChange,
}: {
  readonly ownershipMode: RuntimeOwnershipMode
  readonly qualityTier: VisualQualityTier
  readonly fpsTarget: FpsTarget
  readonly detectedRefreshHz: number
  readonly telemetry: FrameTelemetrySnapshot
  readonly onOwnershipChange: (mode: RuntimeOwnershipMode) => void
  readonly onQualityChange: (tier: VisualQualityTier) => void
  readonly onFpsChange: (fps: FpsTarget) => void
}) {
  const ownershipOptions: ReadonlyArray<{ id: RuntimeOwnershipMode; label: string; desc: string }> = [
    { id: 'none', label: 'Direct Mode Only (0 Runtime)', desc: 'Perintah deterministik penuh offline tanpa memuat LLM.' },
    { id: 'managed_local', label: 'JARVIS-Managed Local', desc: 'Diawasi Job Object KILL_ON_JOB_CLOSE (≤ 5 detik bersih saat tutup).' },
    { id: 'external_local', label: 'Existing Local Runtime', desc: 'Terhubung ke Ollama/llama.cpp milik pengguna — dilarang dimatikan JARVIS (BR-AI-04).' },
    { id: 'authorized_lan', label: 'Authorized Private LAN (R2)', desc: 'Endpoint privat terdaftar eksplisit; tanpa fallback diam-diam lintas zona.' },
    { id: 'custom_compatible', label: 'Custom Compatible Provider', desc: 'Adapter lokal/privat kustom sesuai kontrak ProviderPort.' },
  ]

  return (
    <section className="grid gap-4 md:grid-cols-2">
      <div className="rounded-xl border p-5" style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}>
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <h2 className="text-sm font-semibold">Runtime Ownership Policy (DEC-020)</h2>
        </div>
        <div className="mt-3 space-y-2">
          {ownershipOptions.map((opt) => {
            const active = ownershipMode === opt.id
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => onOwnershipChange(opt.id)}
                className="w-full rounded-lg border p-3 text-left transition-colors hover:bg-[#1c2c44]"
                style={{
                  borderColor: active ? 'var(--accent-core)' : 'var(--border-subtle)',
                  backgroundColor: active ? 'var(--accent-core-dim)' : 'var(--surface-elevated)',
                }}
              >
                <div className="text-xs font-semibold">{opt.label}</div>
                <div className="mt-0.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
                  {opt.desc}
                </div>
              </button>
            )
          })}
        </div>
      </div>

      <div className="space-y-4 rounded-xl border p-5" style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}>
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <h2 className="text-sm font-semibold">Adaptive Visual Engine (DEC-010 & DEC-030)</h2>
        </div>

        <div>
          <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
            Kualitas Visual
          </span>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {(['cinematic', 'balanced', 'lite', 'reduced_motion'] as const).map((tier) => (
              <button
                key={tier}
                type="button"
                onClick={() => onQualityChange(tier)}
                className="font-mono-tabular rounded-lg border px-3 py-2 text-xs font-medium transition-colors hover:bg-[#1c2c44]"
                style={{
                  borderColor: qualityTier === tier ? 'var(--accent-core)' : 'var(--border-subtle)',
                  backgroundColor: qualityTier === tier ? 'var(--accent-core-dim)' : 'var(--surface-elevated)',
                  color: qualityTier === tier ? 'var(--accent-core)' : 'var(--text-primary)',
                }}
              >
                {tier}
              </button>
            ))}
          </div>
        </div>

        <div>
          <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
            Target Frame Rate (Monitor terdeteksi: {detectedRefreshHz} Hz)
          </span>
          <div className="mt-2 flex flex-wrap gap-2">
            {(['auto', '30', '60', '120', 'native'] as const).map((fps) => (
              <button
                key={fps}
                type="button"
                onClick={() => onFpsChange(fps)}
                className="font-mono-tabular rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-[#1c2c44]"
                style={{
                  borderColor: fpsTarget === fps ? 'var(--accent-core)' : 'var(--border-subtle)',
                  backgroundColor: fpsTarget === fps ? 'var(--accent-core-dim)' : 'var(--surface-elevated)',
                  color: fpsTarget === fps ? 'var(--accent-core)' : 'var(--text-primary)',
                }}
              >
                {fps.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div
          className="font-mono-tabular rounded-lg border p-3 text-xs"
          style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-subtle)' }}
        >
          <div style={{ color: 'var(--text-muted)' }}>Telemetri Frame Aktual (bukan angka fiktif):</div>
          <div className="mt-1.5 grid grid-cols-2 gap-2">
            <div>FPS Terukur: {telemetry.measuredFps}</div>
            <div>p50 / p95: {telemetry.p50Ms}ms / {telemetry.p95Ms}ms</div>
            <div>Sampel Frame: {telemetry.renderedFrames}</div>
            <div>Dropped: {telemetry.droppedFrames}</div>
          </div>
        </div>
      </div>
    </section>
  )
}

export function LicenseInventoryPanel({
  artifacts,
}: {
  readonly artifacts: ReadonlyArray<LicenseArtifact>
}) {
  return (
    <section className="space-y-4">
      <div
        className="flex items-center justify-between rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-3">
          <Scale className="h-5 w-5" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <div>
            <h2 className="text-base font-semibold">11-Category Artifact & License Compliance Inventory</h2>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Lisensi Unknown diblokir deterministik (BR-SYS-03). Komponen GPL/AGPL dan aset suara dicatat kewajibannya secara transparan.
            </p>
          </div>
        </div>
        <span className="font-mono-tabular rounded-md border px-2.5 py-1 text-xs" style={{ borderColor: 'var(--border-subtle)' }}>
          {artifacts.length} Artefak Terverifikasi
        </span>
      </div>

      <div className="space-y-2">
        {artifacts.map((art) => (
          <div
            key={art.id}
            className="rounded-xl border p-4"
            style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <span className="font-mono-tabular text-[11px] uppercase" style={{ color: 'var(--text-muted)' }}>
                  [{art.category}]
                </span>
                <h3 className="text-sm font-semibold">
                  {art.name} <span className="font-mono-tabular text-xs font-normal">({art.version_or_rev})</span>
                </h3>
              </div>
              <span
                className="font-mono-tabular rounded-md px-2 py-0.5 text-xs font-semibold"
                style={{
                  backgroundColor: art.license_spdx.includes('GPL')
                    ? 'var(--status-warn-dim)'
                    : 'var(--accent-core-dim)',
                  color: art.license_spdx.includes('GPL') ? 'var(--status-warn)' : 'var(--accent-core)',
                }}
              >
                {art.license_spdx}
              </span>
            </div>
            <p className="mt-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
              {art.notice_text}
            </p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {art.obligations.map((ob) => (
                <span
                  key={ob}
                  className="font-mono-tabular rounded border px-1.5 py-0.5 text-[10px]"
                  style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-muted)' }}
                >
                  {ob}
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
