import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../App'
import { useJarvisStore } from '../store/jarvisStore'

describe('Phase 4 (R2) UI: Knowledge Hybrid RAG, Personal Life & Typed Workflows', () => {
  beforeEach(() => {
    useJarvisStore.setState({
      activeTab: 'command',
      knowledgeRoots: [],
      tasks: [],
      expenseSummaries: [],
      workflows: [],
    })
  })

  it('adds and revokes opt-in Knowledge Base source roots and enforces tools=[] search', async () => {
    render(<App />)
    await waitFor(() => expect(useJarvisStore.getState().capabilities).not.toBeNull())

    fireEvent.click(screen.getByRole('button', { name: /Knowledge \(Hybrid RAG\)/i }))
    fireEvent.change(screen.getByLabelText(/Jalur folder dokumen opt-in/i), {
      target: { value: '<DOCUMENTS>/ResearchNotes' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Izinkan Folder/i }))
    expect(screen.getByText('<DOCUMENTS>/ResearchNotes')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/Cari di Knowledge Base/i), {
      target: { value: 'Argon2id backup' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Cari Sitasi/i }))
    expect(screen.getByText(/Hybrid RRF \(BM25 FTS5/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Cabut Akses/i }))
    expect(screen.getByText(/Status: REVOKED/i)).toBeInTheDocument()
  })

  it('records tasks and isolates IDR vs USD minor-unit expenses without mixing currencies', async () => {
    render(<App />)
    await waitFor(() => expect(useJarvisStore.getState().capabilities).not.toBeNull())

    fireEvent.click(screen.getByRole('button', { name: /Personal Life/i }))
    fireEvent.change(screen.getByLabelText(/Judul task baru/i), {
      target: { value: 'Audit dokumen backup' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^Tambah$/i }))
    expect(screen.getByText('Audit dokumen backup')).toBeInTheDocument()

    // Record IDR expense, then USD expense
    fireEvent.click(screen.getByRole('button', { name: /Catat Pengeluaran Lokal/i }))
    fireEvent.change(screen.getByLabelText(/Mata uang ISO/i), { target: { value: 'USD' } })
    fireEvent.change(screen.getByLabelText(/Nominal minor unit/i), { target: { value: '1999' } })
    fireEvent.click(screen.getByRole('button', { name: /Catat Pengeluaran Lokal/i }))

    expect(screen.getByText(/Net: 50000 minor/i)).toBeInTheDocument()
    expect(screen.getByText(/Net: 1999 minor/i)).toBeInTheDocument()
  })

  it('creates declarative workflow and renders dry-run preview with bound_hash', async () => {
    render(<App />)
    await waitFor(() => expect(useJarvisStore.getState().capabilities).not.toBeNull())

    fireEvent.click(screen.getByRole('button', { name: /^Workflows$/i }))
    fireEvent.change(screen.getByLabelText(/Nama workflow baru/i), {
      target: { value: 'Rutinitas Pagi Aman' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Simpan Workflow/i }))
    expect(screen.getByText('Rutinitas Pagi Aman')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Pratinjau Dry-Run/i }))
    expect(screen.getByText(/Dry-Run 'Rutinitas Pagi Aman'/i)).toBeInTheDocument()
  })
})
