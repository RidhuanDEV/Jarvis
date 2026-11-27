import { useEffect, useRef, useState } from 'react'
import { Clock3, LockKeyhole, ShieldAlert } from 'lucide-react'
import type { ApprovalChallenge } from '../lib/contracts'

interface ApprovalDialogProps {
  readonly challenge: ApprovalChallenge | null
  readonly onApprove: (challenge: ApprovalChallenge) => void
  readonly onReject: (challenge: ApprovalChallenge) => void
  readonly onExpire: (challenge: ApprovalChallenge) => void
}

export function ApprovalDialog({
  challenge,
  onApprove,
  onReject,
  onExpire,
}: ApprovalDialogProps) {
  const dialogRef = useRef<HTMLDialogElement | null>(null)
  const rejectButtonRef = useRef<HTMLButtonElement | null>(null)
  const [nowMs, setNowMs] = useState(() => Date.now())

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) {
      return
    }
    if (challenge) {
      if (!dialog.open && typeof dialog.showModal === 'function') {
        dialog.showModal()
      } else if (!dialog.open) {
        dialog.setAttribute('open', 'true')
      }
      // 10-UX-DESIGN.md §4: Always place initial keyboard focus on the safe Reject button
      rejectButtonRef.current?.focus()
    } else if (dialog.open) {
      if (typeof dialog.close === 'function') {
        dialog.close()
      } else {
        dialog.removeAttribute('open')
      }
    }
  }, [challenge])

  useEffect(() => {
    if (!challenge) {
      return
    }
    const interval = window.setInterval(() => {
      const current = Date.now()
      setNowMs(current)
      if (Date.parse(challenge.expires_at) - current <= 0) {
        window.clearInterval(interval)
        onExpire(challenge)
      }
    }, 500)
    return () => window.clearInterval(interval)
  }, [challenge, onExpire])

  const remainingSec = challenge
    ? Math.max(0, Math.ceil((Date.parse(challenge.expires_at) - nowMs) / 1000))
    : 0
  const progressPct = Math.max(0, Math.min(100, Math.round((remainingSec / 90) * 100)))

  return (
    <dialog
      ref={dialogRef}
      className="jarvis-approval-dialog"
      aria-labelledby="jarvis-r2-title"
      aria-describedby="jarvis-r2-summary"
      onCancel={(ev) => {
        ev.preventDefault()
        if (challenge) {
          onReject(challenge)
        }
      }}
    >
      {challenge && (
        <div>
          {/* Top precision amber security hairline */}
          <div
            className="h-1 w-full"
            style={{
              background:
                'linear-gradient(90deg, rgba(255,190,105,0.2) 0%, #ffbe69 50%, rgba(255,190,105,0.2) 100%)',
            }}
          />

          <div className="p-6">
            <div className="flex items-start justify-between gap-4">
              <div className="flex items-center gap-3.5">
                <div
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border"
                  style={{
                    backgroundColor: 'var(--status-warn-dim)',
                    borderColor: 'rgba(255, 190, 105, 0.35)',
                    color: 'var(--status-warn)',
                  }}
                >
                  <ShieldAlert className="h-5 w-5" aria-hidden="true" />
                </div>
                <div>
                  <span
                    className="font-mono-tabular inline-block rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide"
                    style={{
                      backgroundColor: 'var(--status-warn-dim)',
                      borderColor: 'rgba(255, 190, 105, 0.3)',
                      color: 'var(--status-warn)',
                    }}
                  >
                    RISIKO R2 — PERSETUJUAN LOKAL WAJIB
                  </span>
                  <h2 id="jarvis-r2-title" className="font-display mt-1.5 text-base font-semibold">
                    Konfirmasi Aksi: <span className="font-mono-tabular">{challenge.tool_id}</span> (v
                    {challenge.tool_version})
                  </h2>
                </div>
              </div>
              <div
                className="font-mono-tabular inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-semibold"
                style={{
                  borderColor: remainingSec <= 10 ? 'var(--status-danger)' : 'rgba(255, 190, 105, 0.45)',
                  backgroundColor: remainingSec <= 10 ? 'var(--status-danger-dim)' : 'var(--status-warn-dim)',
                  color: remainingSec <= 10 ? 'var(--status-danger)' : 'var(--status-warn)',
                }}
                aria-label={`Sisa waktu persetujuan ${remainingSec} detik`}
              >
                <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
                {remainingSec}s
              </div>
            </div>

            {/* Countdown freshness gauge */}
            <div
              className="mt-4 h-1 w-full overflow-hidden rounded-full"
              style={{ backgroundColor: 'rgba(126, 173, 226, 0.14)' }}
            >
              <div
                className="h-full rounded-full transition-[width] duration-500"
                style={{
                  width: `${progressPct}%`,
                  backgroundColor: remainingSec <= 10 ? 'var(--status-danger)' : 'var(--status-warn)',
                }}
              />
            </div>

            <p
              id="jarvis-r2-summary"
              className="mt-4 text-sm leading-relaxed"
              style={{ color: 'var(--text-secondary)' }}
            >
              {challenge.summary}
            </p>

            {(challenge.before_preview || challenge.after_preview) && (
              <div className="jarvis-panel-inset mt-4 grid gap-2.5 rounded-xl p-3.5 text-xs">
                {challenge.before_preview && (
                  <div className="flex items-start gap-2">
                    <span
                      className="font-mono-tabular shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold"
                      style={{ backgroundColor: 'var(--status-danger-dim)', color: 'var(--status-danger)' }}
                    >
                      SEBELUM
                    </span>
                    <span className="font-mono-tabular break-all" style={{ color: 'var(--text-secondary)' }}>
                      {challenge.before_preview}
                    </span>
                  </div>
                )}
                {challenge.after_preview &&
                  (challenge.after_preview.includes('\n') &&
                  (challenge.after_preview.includes('@@') ||
                    challenge.after_preview.startsWith('--- ') ||
                    challenge.after_preview.includes('\n+') ||
                    challenge.after_preview.includes('\n-')) ? (
                    <div
                      data-testid="approval-diff-preview"
                      aria-label="Pratinjau perubahan baris unified diff"
                      className="font-mono-tabular max-h-48 overflow-y-auto rounded-lg border p-2.5 text-[11px] leading-relaxed"
                      style={{
                        backgroundColor: 'var(--surface-panel)',
                        borderColor: 'var(--border-strong)',
                      }}
                    >
                      {challenge.after_preview.split('\n').map((line, idx) => {
                        const isAdd = line.startsWith('+') && !line.startsWith('+++')
                        const isDel = line.startsWith('-') && !line.startsWith('---')
                        const isHunk = line.startsWith('@@')
                        return (
                          <div
                            key={`${idx}-${line.slice(0, 12)}`}
                            className="whitespace-pre-wrap break-all rounded px-1.5 py-0.5"
                            style={{
                              color: isAdd
                                ? 'var(--status-ok)'
                                : isDel
                                  ? 'var(--status-danger)'
                                  : isHunk
                                    ? 'var(--accent-core)'
                                    : 'var(--text-secondary)',
                              backgroundColor: isAdd
                                ? 'rgba(94, 234, 212, 0.09)'
                                : isDel
                                  ? 'rgba(255, 115, 124, 0.10)'
                                  : 'transparent',
                            }}
                          >
                            {isAdd && <span className="sr-only">Baris ditambahkan: </span>}
                            {isDel && <span className="sr-only">Baris dihapus: </span>}
                            {line || ' '}
                          </div>
                        )
                      })}
                    </div>
                  ) : (
                    <div className="flex items-start gap-2">
                      <span
                        className="font-mono-tabular shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold"
                        style={{ backgroundColor: 'var(--status-ok-dim)', color: 'var(--status-ok)' }}
                      >
                        SESUDAH
                      </span>
                      <span className="font-mono-tabular break-all" style={{ color: 'var(--accent-core)' }}>
                        {challenge.after_preview}
                      </span>
                    </div>
                  ))}
              </div>
            )}

            {remainingSec > 0 && remainingSec <= 10 && (
              <div
                role="alert"
                className="mt-3 rounded-lg border px-3 py-2 text-xs font-medium"
                style={{
                  borderColor: 'var(--status-danger)',
                  backgroundColor: 'var(--status-danger-dim)',
                  color: 'var(--status-danger)',
                }}
              >
                Peringatan: persetujuan akan kedaluwarsa dalam {remainingSec} detik.
              </div>
            )}

            <div className="jarvis-panel-inset font-mono-tabular mt-4 flex items-start gap-2.5 rounded-xl px-3.5 py-2.5 text-[11px]">
              <LockKeyhole className="mt-0.5 h-3.5 w-3.5 shrink-0" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
              <div style={{ color: 'var(--text-muted)' }}>
                <div>Bound Hash: {challenge.bound_hash.slice(0, 24)}…</div>
                <div className="mt-1">
                  Persetujuan via suara maupun sesi remote diblokir. Gugur otomatis jika sesi terkunci atau target berubah.
                </div>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap justify-end gap-3">
              <button
                ref={rejectButtonRef}
                type="button"
                onClick={() => onReject(challenge)}
                className="rounded-xl border px-4 py-2.5 text-sm font-medium transition-all hover:bg-[#1c304d] active:scale-[0.98]"
                style={{
                  borderColor: 'var(--border-strong)',
                  color: 'var(--text-primary)',
                  backgroundColor: 'var(--surface-elevated)',
                }}
              >
                Tolak (Esc)
              </button>
              <button
                type="button"
                disabled={remainingSec <= 0}
                onClick={() => onApprove(challenge)}
                className="rounded-xl px-5 py-2.5 text-sm font-semibold shadow-md transition-all hover:brightness-110 active:scale-[0.98]"
                style={{
                  backgroundColor: 'var(--status-warn)',
                  color: '#060b14',
                }}
              >
                Setujui Sekali Ini
              </button>
            </div>
          </div>
        </div>
      )}
    </dialog>
  )
}
