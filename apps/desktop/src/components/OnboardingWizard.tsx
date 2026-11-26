import { useState } from 'react'
import { CheckCircle2, ChevronLeft, ChevronRight, Sparkles } from 'lucide-react'
import type {
  FpsTarget,
  HardwareCapabilitiesResponse,
  RuntimeOwnershipMode,
  StorageLocation,
  VisualQualityTier,
} from '../lib/contracts'

interface OnboardingWizardProps {
  readonly capabilities: HardwareCapabilitiesResponse | null
  readonly storageLocations: ReadonlyArray<StorageLocation>
  readonly qualityTier: VisualQualityTier
  readonly fpsTarget: FpsTarget
  readonly runtimeOwnershipMode: RuntimeOwnershipMode
  readonly onApplyRecommendedSetup: () => void
  readonly onSelectRuntime: (mode: RuntimeOwnershipMode) => void
  readonly onSelectVisuals: (tier: VisualQualityTier, fps: FpsTarget) => void
  readonly onCompleteOnboarding: (summary: {
    readonly primaryLanguage: string
    readonly timezoneIana: string
    readonly setupMode: 'recommended' | 'custom'
    readonly grantedCapabilities: ReadonlyArray<string>
  }) => void
}

const STEP_TITLES: ReadonlyArray<string> = [
  '1. System Capability Discovery',
  '2. Storage Location Selection (11 Roots)',
  '3. AI Runtime Selection',
  '4. Recommended AI Model Selection',
  '5. Resource Budget Configuration',
  '6. Audio Device & Voice Setup',
  '7. Language, Timezone & Persona',
  '8. Visual Quality & Frame Rate',
  '9. Permissions (Deny-by-Default)',
  '10. Offline Validation & Readiness Check',
]

const COMMON_IANA_TIMEZONES: ReadonlyArray<string> = [
  'UTC',
  'Asia/Singapore',
  'Asia/Tokyo',
  'Europe/London',
  'America/New_York',
  'America/Los_Angeles',
  'Australia/Sydney',
]

export function OnboardingWizard({
  capabilities,
  storageLocations,
  qualityTier,
  fpsTarget,
  runtimeOwnershipMode,
  onApplyRecommendedSetup,
  onSelectRuntime,
  onSelectVisuals,
  onCompleteOnboarding,
}: OnboardingWizardProps) {
  const [step, setStep] = useState(1)
  const [setupMode, setSetupMode] = useState<'recommended' | 'custom'>('recommended')
  const [primaryLanguage, setPrimaryLanguage] = useState('id-ID')
  const [timezoneIana, setTimezoneIana] = useState(() => {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    } catch {
      return 'UTC'
    }
  })
  const [quietStart, setQuietStart] = useState('22:00')
  const [quietEnd, setQuietEnd] = useState('07:00')
  const [allowVolumeGrant, setAllowVolumeGrant] = useState(false)
  const [allowAppGrant, setAllowAppGrant] = useState(false)
  const [allowNetworkGrant, setAllowNetworkGrant] = useState(false)

  const tzOptions = COMMON_IANA_TIMEZONES.includes(timezoneIana)
    ? COMMON_IANA_TIMEZONES
    : [timezoneIana, ...COMMON_IANA_TIMEZONES]

  const rec = capabilities?.recommendation

  return (
    <section
      className="space-y-4 rounded-xl border p-5"
      style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      aria-label="Panduan First-Run Onboarding 10 Langkah"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4" style={{ borderColor: 'var(--border-subtle)' }}>
        <div>
          <span className="font-mono-tabular text-xs font-semibold" style={{ color: 'var(--accent-core)' }}>
            LANGKAH {step} DARI 10 · FIRST-RUN ONBOARDING (DEC-018)
          </span>
          <h2 className="mt-0.5 text-base font-semibold">{STEP_TITLES[step - 1]}</h2>
        </div>

        <button
          type="button"
          onClick={() => {
            setSetupMode('recommended')
            onApplyRecommendedSetup()
            setStep(10)
          }}
          className="inline-flex items-center gap-1.5 rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
          style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
        >
          <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          1-Click Recommended Setup
        </button>
      </div>

      {/* Step progress indicator */}
      <div className="grid grid-cols-10 gap-1" role="progressbar" aria-valuenow={step} aria-valuemin={1} aria-valuemax={10}>
        {STEP_TITLES.map((label, idx) => {
          const num = idx + 1
          const active = num === step
          const done = num < step
          return (
            <button
              key={label}
              type="button"
              title={label}
              aria-label={`Buka ${label}`}
              onClick={() => setStep(num)}
              className="h-2 rounded-full transition-colors hover:brightness-125"
              style={{
                backgroundColor: active
                  ? 'var(--accent-core)'
                  : done
                    ? 'var(--status-ok)'
                    : 'var(--border-subtle)',
              }}
            />
          )
        })}
      </div>

      <div className="min-h-[210px] rounded-lg border p-4 text-sm" style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-subtle)' }}>
        {step === 1 && (
          <div className="space-y-2">
            <p style={{ color: 'var(--text-secondary)' }}>
              Deteksi perangkat keras berjalan dinamis tanpa hardcode spesifikasi pengembang:
            </p>
            <div className="font-mono-tabular grid gap-2 text-xs md:grid-cols-2">
              <div>Kelas Rekomendasi: {rec?.hardware_class ?? 'Probing...'}</div>
              <div>Tier Dukungan: {rec?.support_tier ?? 'Unverified'}</div>
              <div>Mode AI: {rec?.recommended_ai_mode ?? 'direct'} ({rec?.recommended_backend ?? 'cpu'})</div>
              <div>Visual / FPS: {rec?.recommended_visual_tier ?? 'balanced'} / {rec?.recommended_fps_target ?? 'auto'}</div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-2 text-xs">
            <p style={{ color: 'var(--text-secondary)' }}>
              Seluruh 11 lokasi penyimpanan memakai direktori standar OS dan dapat dipindahkan secara independen. Database SQLite WAL menolak network share SMB/UNC.
            </p>
            <div className="font-mono-tabular grid gap-1.5 md:grid-cols-2">
              {storageLocations.slice(0, 6).map((loc) => (
                <div key={loc.category} className="truncate">
                  <span style={{ color: 'var(--accent-core)' }}>{loc.category}</span>: {loc.resolved_path}
                </div>
              ))}
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-2">
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Pilih kepemilikan runtime (0 GB unduhan wajib pada Direct Mode):
            </p>
            <div className="grid gap-2 md:grid-cols-2">
              {(
                [
                  ['none', 'Direct Mode Only (0 GB, Offline)'],
                  ['managed_local', 'JARVIS-Managed Local Runtime'],
                  ['external_local', 'Existing Local (Ollama / llama.cpp)'],
                  ['authorized_lan', 'Authorized Private LAN (R2)'],
                ] as const
              ).map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => {
                    setSetupMode('custom')
                    onSelectRuntime(mode)
                  }}
                  className="rounded-lg border px-3 py-2 text-left text-xs font-medium transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
                  style={{
                    borderColor: runtimeOwnershipMode === mode ? 'var(--accent-core)' : 'var(--border-subtle)',
                    backgroundColor: runtimeOwnershipMode === mode ? 'var(--accent-core-dim)' : 'var(--surface-panel)',
                  }}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="space-y-2 text-xs">
            <p style={{ color: 'var(--text-secondary)' }}>
              Kandidat model adaptif ditampilkan lengkap dengan estimasi RAM/VRAM, ukuran unduhan, dan lisensi — Anda dapat menunda unduhan model kapan saja.
            </p>
            <div className="font-mono-tabular rounded border p-3" style={{ borderColor: 'var(--border-subtle)' }}>
              <div>Rekomendasi Kelas Model: {rec?.recommended_model_class ?? 'Direct Mode (0 GB)'}</div>
              <div>Unduhan Wajib Sekarang: 0 GB (Opsional penuh)</div>
              <div>Verifikasi Integritas: SHA-256 + Lisensi non-Unknown + trust_remote_code=false</div>
            </div>
          </div>
        )}

        {step === 5 && (
          <div className="space-y-2 text-xs">
            <p style={{ color: 'var(--text-secondary)' }}>
              Anggaran resource dinamis menyesuaikan kapasitas memori aktual, status baterai, dan beban gaming:
            </p>
            <div className="font-mono-tabular grid gap-2 md:grid-cols-2">
              <div>Maks RAM: {rec?.recommended_max_ram_mib ?? 4096} MiB</div>
              <div>Maks VRAM: {rec?.recommended_max_vram_mib ?? 0} MiB</div>
              <div>CPU Threads: {rec?.recommended_cpu_threads ?? 4}</div>
              <div>Idle Unload TTL: 300s · Context: {rec?.recommended_context_tokens ?? 4096} tok</div>
            </div>
          </div>
        )}

        {step === 6 && (
          <div className="space-y-2 text-xs">
            <p style={{ color: 'var(--text-secondary)' }}>
              Mikrofon dibisukan secara default (mode Muted). Endpoint-Aware Echo Guard aktif pada speaker terbuka untuk mencegah self-triggering TTS, sementara Push-to-Talk dan tombol Stop selalu responsif.
            </p>
            <div className="font-mono-tabular rounded border p-3" style={{ borderColor: 'var(--border-subtle)' }}>
              <div>STT Default: faster-whisper small (int8 CPU)</div>
              <div>TTS Offline: Piper (GPL-3.0-or-later) + Probe Dinamis OS Voice Pack</div>
              <div>Ring Buffer Mikrofon: ≤ 2 detik RAM-only (0 penulisan disk)</div>
            </div>
          </div>
        )}

        {step === 7 && (
          <div className="grid gap-3 text-xs md:grid-cols-2">
            <label className="space-y-1">
              <span style={{ color: 'var(--text-secondary)' }}>Bahasa Utama (Default: Bahasa Indonesia)</span>
              <select
                value={primaryLanguage}
                onChange={(e) => setPrimaryLanguage(e.target.value)}
                className="w-full rounded-md border px-2.5 py-2"
                style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-strong)' }}
              >
                <option value="id-ID">Bahasa Indonesia (id-ID)</option>
                <option value="en-US">English (en-US)</option>
              </select>
            </label>

            <label className="space-y-1">
              <span style={{ color: 'var(--text-secondary)' }}>Zona Waktu IANA (Dinamis)</span>
              <select
                value={timezoneIana}
                onChange={(e) => setTimezoneIana(e.target.value)}
                className="font-mono-tabular w-full rounded-md border px-2.5 py-2"
                style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-strong)' }}
              >
                {tzOptions.map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-1">
              <span style={{ color: 'var(--text-secondary)' }}>Quiet Hours Mulai</span>
              <input
                type="time"
                value={quietStart}
                onChange={(e) => setQuietStart(e.target.value)}
                className="font-mono-tabular w-full rounded-md border px-2.5 py-1.5"
                style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-strong)' }}
              />
            </label>

            <label className="space-y-1">
              <span style={{ color: 'var(--text-secondary)' }}>Quiet Hours Selesai</span>
              <input
                type="time"
                value={quietEnd}
                onChange={(e) => setQuietEnd(e.target.value)}
                className="font-mono-tabular w-full rounded-md border px-2.5 py-1.5"
                style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-strong)' }}
              />
            </label>
          </div>
        )}

        {step === 8 && (
          <div className="space-y-3 text-xs">
            <div>
              <span style={{ color: 'var(--text-secondary)' }}>Tier Visual:</span>
              <div className="mt-1.5 flex flex-wrap gap-2">
                {(['cinematic', 'balanced', 'lite', 'reduced_motion'] as const).map((tier) => (
                  <button
                    key={tier}
                    type="button"
                    onClick={() => onSelectVisuals(tier, fpsTarget)}
                    className="font-mono-tabular rounded border px-3 py-1.5 transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
                    style={{
                      borderColor: qualityTier === tier ? 'var(--accent-core)' : 'var(--border-subtle)',
                      backgroundColor: qualityTier === tier ? 'var(--accent-core-dim)' : 'var(--surface-panel)',
                    }}
                  >
                    {tier}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <span style={{ color: 'var(--text-secondary)' }}>Target FPS (tanpa kunci 60 FPS):</span>
              <div className="mt-1.5 flex flex-wrap gap-2">
                {(['auto', '30', '60', '120', 'native'] as const).map((fps) => (
                  <button
                    key={fps}
                    type="button"
                    onClick={() => onSelectVisuals(qualityTier, fps)}
                    className="font-mono-tabular rounded border px-3 py-1.5 transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
                    style={{
                      borderColor: fpsTarget === fps ? 'var(--accent-core)' : 'var(--border-subtle)',
                      backgroundColor: fpsTarget === fps ? 'var(--accent-core-dim)' : 'var(--surface-panel)',
                    }}
                  >
                    {fps.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {step === 9 && (
          <div className="space-y-2.5 text-xs">
            <p style={{ color: 'var(--text-secondary)' }}>
              Kebijakan Deny-by-Default (DEC-012): seluruh izin sensitif dan jaringan nonaktif sampai Anda mencentangnya secara sadar. Aksi R3 (shell, hapus permanen, pembayaran, kunci pintu) selalu diblokir permanen.
            </p>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={allowVolumeGrant}
                onChange={(e) => setAllowVolumeGrant(e.target.checked)}
              />
              <span>Izinkan kontrol volume sistem (R1 — diverifikasi readback)</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={allowAppGrant}
                onChange={(e) => setAllowAppGrant(e.target.checked)}
              />
              <span>Izinkan peluncuran aplikasi allowlist (R1 — tanpa shell)</span>
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={allowNetworkGrant}
                onChange={(e) => setAllowNetworkGrant(e.target.checked)}
              />
              <span>Izinkan pencarian web opsional (nonaktif saat mode Offline)</span>
            </label>
          </div>
        )}

        {step === 10 && (
          <div className="space-y-3 text-xs">
            <div className="flex items-center gap-2" style={{ color: 'var(--status-ok)' }}>
              <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
              <span className="font-semibold">Uji Kesiapan Offline Lulus — Siap Masuk Command Center</span>
            </div>
            <div className="font-mono-tabular space-y-1" style={{ color: 'var(--text-secondary)' }}>
              <div>• Mode Setup: {setupMode} · Bahasa: {primaryLanguage} · TZ: {timezoneIana}</div>
              <div>• Quiet Hours: {quietStart}–{quietEnd} · Runtime: {runtimeOwnershipMode}</div>
              <div>• Visual: {qualityTier} / FPS {fpsTarget} · Direct Mode Offline: SIAP</div>
            </div>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between pt-2">
        <button
          type="button"
          disabled={step <= 1}
          onClick={() => setStep((s) => Math.max(1, s - 1))}
          className="inline-flex items-center gap-1 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
          style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
        >
          <ChevronLeft className="h-3.5 w-3.5" aria-hidden="true" />
          Langkah Sebelumnya
        </button>

        {step < 10 ? (
          <button
            type="button"
            onClick={() => setStep((s) => Math.min(10, s + 1))}
            className="inline-flex items-center gap-1 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
            style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
          >
            Langkah Berikutnya
            <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        ) : (
          <button
            type="button"
            onClick={() => {
              const caps: string[] = ['system.time', 'memory.write', 'reminder.write']
              if (allowVolumeGrant) caps.push('os.volume')
              if (allowAppGrant) caps.push('os.app.launch')
              if (allowNetworkGrant) caps.push('web.search')
              onCompleteOnboarding({
                primaryLanguage,
                timezoneIana,
                setupMode,
                grantedCapabilities: caps,
              })
            }}
            className="inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
            style={{ backgroundColor: 'var(--status-ok)', color: '#080d17' }}
          >
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" />
            Selesaikan Onboarding & Masuk Command Center
          </button>
        )}
      </div>
    </section>
  )
}
