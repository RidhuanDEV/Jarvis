import { useEffect, useRef, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
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
        <div className="p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-center gap-3">
              <div
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
                style={{ backgroundColor: 'var(--status-warn-dim)', color: 'var(--status-warn)' }}
              >
                <ShieldAlert className="h-5 w-5" aria-hidden="true" />
              </div>
              <div>
                <span
                  className="font-mono-tabular inline-block rounded px-1.5 py-0.5 text-xs font-semibold"
                  style={{ backgroundColor: 'var(--status-warn-dim)', color: 'var(--status-warn)' }}
                >
                  RISIKO R2 — PERSETUJUAN LOKAL WAJIB
                </span>
                <h2 id="jarvis-r2-title" className="mt-1 text-base font-semibold">
                  Konfirmasi Aksi: <span className="font-mono-tabular">{challenge.tool_id}</span> (v
                  {challenge.tool_version})
                </h2>
              </div>
            </div>
            <div
              className="font-mono-tabular rounded-md border px-2.5 py-1 text-xs font-semibold"
              style={{ borderColor: 'var(--status-warn)', color: 'var(--status-warn)' }}
              aria-label={`Sisa waktu persetujuan ${remainingSec} detik`}
            >
              {remainingSec}s
            </div>
          </div>

          <p
            id="jarvis-r2-summary"
            className="mt-4 text-sm leading-relaxed"
            style={{ color: 'var(--text-secondary)' }}
          >
            {challenge.summary}
          </p>

          {(challenge.before_preview || challenge.after_preview) && (
            <div
              className="mt-4 grid gap-2 rounded-lg border p-3 text-xs"
              style={{
                backgroundColor: 'var(--surface-canvas)',
                borderColor: 'var(--border-subtle)',
              }}
            >
              {challenge.before_preview && (
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Sebelum: </span>
                  <span className="font-mono-tabular">{challenge.before_preview}</span>
                </div>
              )}
              {challenge.after_preview && (
                <div>
                  <span style={{ color: 'var(--text-muted)' }}>Sesudah: </span>
                  <span className="font-mono-tabular" style={{ color: 'var(--accent-core)' }}>
                    {challenge.after_preview}
                  </span>
                </div>
              )}
            </div>
          )}

          <div
            className="font-mono-tabular mt-4 rounded-md border px-3 py-2 text-xs"
            style={{
              backgroundColor: 'var(--surface-canvas)',
              borderColor: 'var(--border-subtle)',
              color: 'var(--text-muted)',
            }}
          >
            <div>Bound Hash: {challenge.bound_hash.slice(0, 24)}…</div>
            <div className="mt-1">
              Persetujuan via suara maupun sesi remote diblokir. Gugur otomatis jika sesi terkunci atau target berubah.
            </div>
          </div>

          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <button
              ref={rejectButtonRef}
              type="button"
              onClick={() => onReject(challenge)}
              className="rounded-lg border px-4 py-2 text-sm font-medium transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
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
              className="rounded-lg px-4 py-2 text-sm font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
              style={{
                backgroundColor: 'var(--status-warn)',
                color: '#080d17',
              }}
            >
              Setujui Sekali Ini
            </button>
          </div>
        </div>
      )}
    </dialog>
  )
}
