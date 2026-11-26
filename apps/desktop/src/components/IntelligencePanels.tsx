import { useState } from 'react'
import { Bell, Brain, Check, Lock, Trash2 } from 'lucide-react'
import type { MemoryItem, ReminderItem } from '../lib/contracts'

export function MemoryVaultPanel({
  memories,
  onCreateMemory,
  onApproveProposal,
  onDeleteMemory,
}: {
  readonly memories: ReadonlyArray<MemoryItem>
  readonly onCreateMemory: (input: {
    readonly kind: 'fact' | 'preference' | 'instruction' | 'note'
    readonly content: string
    readonly sensitivity: 'normal' | 'sensitive'
  }) => void
  readonly onApproveProposal: (id: string, revision: number) => void
  readonly onDeleteMemory: (id: string) => void
}) {
  const [content, setContent] = useState('')
  const [kind, setKind] = useState<'fact' | 'preference' | 'instruction' | 'note'>('fact')
  const [sensitivity, setSensitivity] = useState<'normal' | 'sensitive'>('normal')

  const handleSubmit = (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!content.trim()) return
    onCreateMemory({ kind, content: content.trim(), sensitivity })
    setContent('')
  }

  return (
    <section className="space-y-4">
      <div
        className="rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-2.5">
          <Brain className="h-5 w-5" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <div>
            <h2 className="text-base font-semibold">Memory Vault (Eksplisit & Terenkripsi AES-256-GCM)</h2>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Proposal preferensi tidak dipakai sebagai fakta sebelum disetujui (BR-14). Penghapusan dicatat pada deletion_ledger agar tidak hidup kembali saat restore (T13).
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 grid gap-2.5 md:grid-cols-[1fr_auto_auto_auto]">
          <input
            type="text"
            aria-label="Isi memori baru"
            placeholder="Catat fakta atau preferensi personal secara eksplisit..."
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="rounded-lg border px-3 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <select
            aria-label="Jenis memori"
            value={kind}
            onChange={(e) => {
              const v = e.target.value
              if (v === 'fact' || v === 'preference' || v === 'instruction' || v === 'note') {
                setKind(v)
              }
            }}
            className="rounded-lg border px-2.5 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-elevated)', borderColor: 'var(--border-strong)' }}
          >
            <option value="fact">Fact</option>
            <option value="preference">Preference</option>
            <option value="instruction">Instruction</option>
            <option value="note">Note</option>
          </select>
          <select
            aria-label="Sensitivitas memori"
            value={sensitivity}
            onChange={(e) => {
              const v = e.target.value
              if (v === 'normal' || v === 'sensitive') setSensitivity(v)
            }}
            className="rounded-lg border px-2.5 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-elevated)', borderColor: 'var(--border-strong)' }}
          >
            <option value="normal">Normal</option>
            <option value="sensitive">Sensitive (AES-GCM)</option>
          </select>
          <button
            type="submit"
            className="rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
            style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
          >
            Simpan Memori
          </button>
        </form>
      </div>

      <div className="space-y-2">
        {memories.length === 0 && (
          <div className="rounded-xl border p-5 text-xs" style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)', color: 'var(--text-muted)' }}>
            Belum ada memori tersimpan. Tambahkan memori secara eksplisit di atas atau lewat perintah &quot;ingat bahwa ...&quot;.
          </div>
        )}
        {memories.map((m) => (
          <div
            key={m.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
            style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
          >
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-[11px]">
                <span className="font-mono-tabular uppercase" style={{ color: 'var(--text-muted)' }}>
                  [{m.kind}] rev {m.revision}
                </span>
                {m.is_encrypted && (
                  <span
                    className="font-mono-tabular inline-flex items-center gap-1 rounded px-1.5 py-0.5"
                    style={{ backgroundColor: 'var(--accent-core-dim)', color: 'var(--accent-core)' }}
                  >
                    <Lock className="h-3 w-3" aria-hidden="true" />
                    AES-256-GCM
                  </span>
                )}
                {m.status === 'proposal' && (
                  <span
                    className="font-mono-tabular rounded px-1.5 py-0.5"
                    style={{ backgroundColor: 'var(--status-warn-dim)', color: 'var(--status-warn)' }}
                  >
                    PROPOSAL TERTUNDA
                  </span>
                )}
              </div>
              <p className="mt-1 text-sm">{m.content}</p>
            </div>

            <div className="flex items-center gap-2">
              {m.status === 'proposal' && (
                <button
                  type="button"
                  onClick={() => onApproveProposal(m.id, m.revision)}
                  className="inline-flex items-center gap-1 rounded-md px-2.5 py-1.5 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
                  style={{ backgroundColor: 'var(--status-ok)', color: '#080d17' }}
                >
                  <Check className="h-3.5 w-3.5" aria-hidden="true" />
                  Setujui
                </button>
              )}
              <button
                type="button"
                aria-label={`Hapus memori ${m.id}`}
                onClick={() => onDeleteMemory(m.id)}
                className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-xs transition-colors hover:bg-[#ff737c]/15 active:scale-[0.99]"
                style={{ borderColor: 'var(--status-danger)', color: 'var(--status-danger)' }}
              >
                <Trash2 className="h-3.5 w-3.5" aria-hidden="true" />
                Hapus
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

export function RemindersPanel({
  reminders,
  defaultTimezone,
  onCreateReminder,
  onDismissReminder,
}: {
  readonly reminders: ReadonlyArray<ReminderItem>
  readonly defaultTimezone: string
  readonly onCreateReminder: (input: {
    readonly title: string
    readonly minutesFromNow: number
    readonly timezoneIana: string
  }) => void
  readonly onDismissReminder: (id: string, revision: number) => void
}) {
  const [title, setTitle] = useState('')
  const [minutes, setMinutes] = useState(15)

  const handleSubmit = (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!title.trim()) return
    onCreateReminder({ title: title.trim(), minutesFromNow: minutes, timezoneIana: defaultTimezone })
    setTitle('')
  }

  return (
    <section className="space-y-4">
      <div
        className="rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-2.5">
          <Bell className="h-5 w-5" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <div>
            <h2 className="text-base font-semibold">Pengingat Persisten UTC + Zona Waktu IANA</h2>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Menghormati Quiet Hours lokal (BR-10), deduplikasi restart, dan rekonsiliasi jujur saat perangkat tidur/mati (BR-21). Zona aktif:{' '}
              <span className="font-mono-tabular">{defaultTimezone}</span>.
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 grid gap-2.5 md:grid-cols-[1fr_120px_auto]">
          <input
            type="text"
            aria-label="Judul pengingat baru"
            placeholder="Contoh: Minum air dan istirahatkan mata..."
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="rounded-lg border px-3 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <input
            type="number"
            min={1}
            max={1440}
            aria-label="Menit dari sekarang"
            value={minutes}
            onChange={(e) => setMinutes(Math.max(1, Number.parseInt(e.target.value || '1', 10)))}
            className="font-mono-tabular rounded-lg border px-3 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <button
            type="submit"
            className="rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
            style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
          >
            Jadwalkan (+{minutes}m)
          </button>
        </form>
      </div>

      <div className="space-y-2">
        {reminders.length === 0 && (
          <div className="rounded-xl border p-5 text-xs" style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)', color: 'var(--text-muted)' }}>
            Belum ada pengingat terjadwal.
          </div>
        )}
        {reminders.map((rem) => (
          <div
            key={rem.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
            style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
          >
            <div>
              <div className="text-sm font-medium">{rem.title}</div>
              <div className="font-mono-tabular mt-0.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
                UTC: {rem.due_at_utc} · TZ: {rem.timezone_iana} · Status: {rem.state.toUpperCase()}
              </div>
            </div>
            {rem.state !== 'dismissed' && (
              <button
                type="button"
                onClick={() => onDismissReminder(rem.id, rem.revision)}
                className="rounded-md border px-2.5 py-1.5 text-xs transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
                style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
              >
                Tandai Selesai
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  )
}
