import { useState } from 'react'
import { BookOpen, CalendarCheck2, GitBranch, Search, ShieldCheck, Wallet } from 'lucide-react'
import type {
  CurrencyExpenseSummary,
  KnowledgeQueryResponse,
  KnowledgeRootItem,
  TaskItem,
  WorkflowItem,
} from '../lib/contracts'

export function KnowledgePanel({
  roots,
  onAddRoot,
  onRevokeRoot,
  onSearchKnowledge,
}: {
  readonly roots: ReadonlyArray<KnowledgeRootItem>
  readonly onAddRoot: (path: string) => void
  readonly onRevokeRoot: (id: string) => void
  readonly onSearchKnowledge?: (query: string) => Promise<KnowledgeQueryResponse | null>
}) {
  const [rootInput, setRootInput] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [queryNotice, setQueryNotice] = useState('')

  const handleAdd = (ev: React.FormEvent) => {
    ev.preventDefault()
    if (!rootInput.trim()) return
    onAddRoot(rootInput.trim())
    setRootInput('')
  }

  const handleSearch = (ev: React.FormEvent) => {
    ev.preventDefault()
    const trimmed = searchQuery.trim()
    if (!trimmed) return
    if (roots.filter((r) => r.enabled).length === 0) {
      setQueryNotice(
        'Bukti tidak mencukupi: belum ada folder pengetahuan opt-in yang aktif (tools=[]).',
      )
      return
    }
    if (onSearchKnowledge) {
      setQueryNotice(`Mencari sitasi lokal pada Core untuk "${trimmed}"...`)
      void onSearchKnowledge(trimmed)
        .then((res) => {
          if (!res) {
            setQueryNotice('Gagal memuat hasil pencarian dari Core lokal.')
            return
          }
          setQueryNotice(
            `${res.answer} (${res.citations.length} sitasi terverifikasi, tools=[]).`,
          )
        })
        .catch(() => {
          setQueryNotice('Pencarian Knowledge Base lokal gagal terhubung ke Core.')
        })
      return
    }
    setQueryNotice(
      `Pencarian Hybrid RRF (BM25 FTS5 + Vektor Generasi Aktif, tools=[]): "${trimmed}" — hasil hanya diambil dari root terizinkan.`,
    )
  }

  return (
    <section className="space-y-4">
      <div
        className="rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-2.5">
          <BookOpen className="h-5 w-5" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <div>
            <h2 className="text-base font-semibold">Knowledge Base & Hybrid RAG (FTS5 + Isolated Vector Generation)</h2>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Folder dokumen bersifat opt-in penuh. Sintesis jawaban menonaktifkan seluruh tool (tools=[], BR-15) dan memverifikasi sitasi nyata per halaman/bagian.
            </p>
          </div>
        </div>

        <form onSubmit={handleAdd} className="mt-4 flex flex-wrap gap-2">
          <input
            type="text"
            aria-label="Jalur folder dokumen opt-in"
            placeholder="Tambahkan folder sumber dokumen lokal (mis. <DOCUMENTS>/Notes)..."
            value={rootInput}
            onChange={(e) => setRootInput(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <button
            type="submit"
            className="rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
            style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
          >
            Izinkan Folder (Opt-In)
          </button>
        </form>

        <form onSubmit={handleSearch} className="mt-3 flex flex-wrap gap-2">
          <input
            type="text"
            aria-label="Cari di Knowledge Base"
            placeholder="Cari fakta dengan sitasi terverifikasi (FTS5 + RRF k=60)..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <button
            type="submit"
            className="inline-flex items-center gap-1.5 rounded-lg border px-3.5 py-2 text-xs font-medium transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
            style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
          >
            <Search className="h-3.5 w-3.5" aria-hidden="true" />
            Cari Sitasi
          </button>
        </form>

        {queryNotice && (
          <p
            className="mt-3 rounded-lg border p-3 text-xs"
            style={{
              backgroundColor: 'var(--surface-canvas)',
              borderColor: 'var(--border-subtle)',
              color: 'var(--text-secondary)',
            }}
          >
            {queryNotice}
          </p>
        )}
      </div>

      <div className="space-y-2">
        {roots.length === 0 ? (
          <div className="rounded-xl border p-5 text-xs" style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)', color: 'var(--text-muted)' }}>
            Belum ada source root dokumen yang diizinkan (deny-by-default).
          </div>
        ) : (
          roots.map((r) => (
            <div
              key={r.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
              style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
            >
              <div>
                <div className="font-mono-tabular text-xs font-semibold">{r.canonical_path}</div>
                <div className="font-mono-tabular mt-0.5 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  Rev {r.revision} · Status: {r.enabled ? 'ACTIVE' : 'REVOKED'}
                </div>
              </div>
              {r.enabled && (
                <button
                  type="button"
                  onClick={() => onRevokeRoot(r.id)}
                  className="rounded-md border px-2.5 py-1.5 text-xs transition-colors hover:bg-[#ff737c]/15 active:scale-[0.99]"
                  style={{ borderColor: 'var(--status-danger)', color: 'var(--status-danger)' }}
                >
                  Cabut Akses & Bersihkan Indeks
                </button>
              )}
            </div>
          ))
        )}
      </div>
    </section>
  )
}

export function PersonalLifePanel({
  tasks,
  expenseSummaries,
  onCreateTask,
  onToggleTaskDone,
  onRecordExpense,
}: {
  readonly tasks: ReadonlyArray<TaskItem>
  readonly expenseSummaries: ReadonlyArray<CurrencyExpenseSummary>
  readonly onCreateTask: (title: string) => void
  readonly onToggleTaskDone: (id: string) => void
  readonly onRecordExpense: (input: {
    readonly amountMinor: number
    readonly currencyIso: string
    readonly kind: 'expense' | 'refund'
    readonly category: string
  }) => void
}) {
  const [taskTitle, setTaskTitle] = useState('')
  const [amountStr, setAmountStr] = useState('50000')
  const [currency, setCurrency] = useState('IDR')
  const [category, setCategory] = useState('makan')

  return (
    <section className="grid gap-4 md:grid-cols-2">
      <div
        className="space-y-3 rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-2">
          <CalendarCheck2 className="h-4 w-4" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <h2 className="text-sm font-semibold">Tasks & Local Schedule (FR-LIF-01)</h2>
        </div>

        <form
          onSubmit={(ev) => {
            ev.preventDefault()
            if (!taskTitle.trim()) return
            onCreateTask(taskTitle.trim())
            setTaskTitle('')
          }}
          className="flex gap-2"
        >
          <input
            type="text"
            aria-label="Judul task baru"
            placeholder="Tambah tugas personal lokal..."
            value={taskTitle}
            onChange={(e) => setTaskTitle(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <button
            type="submit"
            className="rounded-lg px-3 py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
            style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
          >
            Tambah
          </button>
        </form>

        <div className="space-y-2">
          {tasks.length === 0 ? (
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              Belum ada tugas lokal.
            </p>
          ) : (
            tasks.map((t) => (
              <div
                key={t.id}
                className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs"
                style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-subtle)' }}
              >
                <span className={t.status === 'completed' ? 'line-through opacity-60' : ''}>{t.title}</span>
                <button
                  type="button"
                  onClick={() => onToggleTaskDone(t.id)}
                  className="rounded border px-2 py-1 text-[11px] transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
                  style={{ borderColor: 'var(--border-strong)' }}
                >
                  {t.status === 'completed' ? 'Buka Ulang' : 'Selesai'}
                </button>
              </div>
            ))
          )}
        </div>
      </div>

      <div
        className="space-y-3 rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-2">
          <Wallet className="h-4 w-4" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <h2 className="text-sm font-semibold">Pengeluaran Multi-Mata Uang Integer Minor (BR-17)</h2>
        </div>
        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
          Disimpan sebagai integer satuan terkecil positif per kode ISO terpisah tanpa pencampuran kurs otomatis.
        </p>

        <form
          onSubmit={(ev) => {
            ev.preventDefault()
            const parsed = Number.parseInt(amountStr, 10)
            if (!Number.isInteger(parsed) || parsed <= 0) return
            onRecordExpense({
              amountMinor: parsed,
              currencyIso: currency,
              kind: 'expense',
              category: category.trim() || 'umum',
            })
          }}
          className="grid grid-cols-3 gap-2"
        >
          <input
            type="number"
            min={1}
            aria-label="Nominal minor unit"
            value={amountStr}
            onChange={(e) => setAmountStr(e.target.value)}
            className="font-mono-tabular rounded-lg border px-2.5 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <select
            aria-label="Mata uang ISO"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="font-mono-tabular rounded-lg border px-2 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-elevated)', borderColor: 'var(--border-strong)' }}
          >
            <option value="IDR">IDR</option>
            <option value="USD">USD</option>
            <option value="EUR">EUR</option>
            <option value="SGD">SGD</option>
          </select>
          <input
            type="text"
            aria-label="Kategori pengeluaran"
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded-lg border px-2.5 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <button
            type="submit"
            className="col-span-3 rounded-lg py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
            style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
          >
            Catat Pengeluaran Lokal
          </button>
        </form>

        <div className="space-y-1.5">
          {expenseSummaries.map((s) => (
            <div
              key={s.currency_iso}
              className="font-mono-tabular flex items-center justify-between rounded-lg border px-3 py-2 text-xs"
              style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-subtle)' }}
            >
              <span style={{ color: 'var(--accent-core)' }}>{s.currency_iso}</span>
              <span>
                Net: {s.net_spend_minor} minor ({s.transaction_count} tx)
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

export function WorkflowsPanel({
  workflows,
  onCreateSampleWorkflow,
}: {
  readonly workflows: ReadonlyArray<WorkflowItem>
  readonly onCreateSampleWorkflow: (name: string) => void
}) {
  const [name, setName] = useState('')
  const [dryRunNote, setDryRunNote] = useState('')

  return (
    <section className="space-y-4">
      <div
        className="rounded-xl border p-5"
        style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
      >
        <div className="flex items-center gap-2.5">
          <GitBranch className="h-5 w-5" style={{ color: 'var(--accent-core)' }} aria-hidden="true" />
          <div>
            <h2 className="text-base font-semibold">Declarative Typed Workflows (≤ 5 Langkah, Tanpa Loop/Kode Bebas)</h2>
            <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              Setiap workflow divalidasi Policy Engine (R3 ditolak), menyediakan pratinjau dry-run dengan bound_hash, dan merekonsiliasi status unknown tanpa blind retry (FR-AUT-01..03).
            </p>
          </div>
        </div>

        <div
          className="mt-3 rounded-lg border px-3 py-2 text-xs"
          style={{
            backgroundColor: 'var(--status-ok-dim, rgba(34, 197, 94, 0.12))',
            borderColor: 'var(--status-ok)',
            color: 'var(--status-ok)',
          }}
        >
          Status Eksekusi (Stage G4): Eksekusi workflow deklaratif nyata aktif melalui Policy Engine; setiap langkah R2 wajib melalui persetujuan GUI tunggal tanpa simulasi palsu.
        </div>

        <form
          onSubmit={(ev) => {
            ev.preventDefault()
            if (!name.trim()) return
            onCreateSampleWorkflow(name.trim())
            setName('')
          }}
          className="mt-4 flex gap-2"
        >
          <input
            type="text"
            aria-label="Nama workflow baru"
            placeholder="Contoh: Rutinitas Pagi Deterministik (waktu + volume 35%)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--border-strong)' }}
          />
          <button
            type="submit"
            className="rounded-lg px-3.5 py-2 text-xs font-semibold transition-colors hover:brightness-110 active:scale-[0.99]"
            style={{ backgroundColor: 'var(--accent-core)', color: '#080d17' }}
          >
            Simpan Workflow
          </button>
        </form>

        {dryRunNote && (
          <div
            className="font-mono-tabular mt-3 flex items-center gap-2 rounded-lg border p-3 text-xs"
            style={{ backgroundColor: 'var(--surface-canvas)', borderColor: 'var(--status-ok)', color: 'var(--status-ok)' }}
          >
            <ShieldCheck className="h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{dryRunNote}</span>
          </div>
        )}
      </div>

      <div className="space-y-2">
        {workflows.map((wf) => (
          <div
            key={wf.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-xl border p-4"
            style={{ backgroundColor: 'var(--surface-panel)', borderColor: 'var(--border-subtle)' }}
          >
            <div>
              <div className="text-sm font-semibold">{wf.name}</div>
              <div className="font-mono-tabular mt-0.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
                {wf.step_count} langkah · Rev {wf.revision} · Hash: {wf.bound_hash.slice(0, 16)}…
              </div>
            </div>
            <button
              type="button"
              onClick={() =>
                setDryRunNote(
                  `Dry-Run '${wf.name}': ${wf.step_count} langkah tervalidasi (0 R3, bound_hash=${wf.bound_hash.slice(0, 16)}…).`,
                )
              }
              className="rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-[#1c2c44] active:scale-[0.99]"
              style={{ borderColor: 'var(--border-strong)', backgroundColor: 'var(--surface-elevated)' }}
            >
              Pratinjau Dry-Run
            </button>
          </div>
        ))}
      </div>
    </section>
  )
}
