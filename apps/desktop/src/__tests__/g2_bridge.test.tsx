import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { PersonalLifePanel, WorkflowsPanel } from '../components/ProductivityPanels'
import { useJarvisStore } from '../store/jarvisStore'

describe('Stage G2 (B08) UI Bridge, Hydration & Defect Regressions', () => {
  beforeEach(() => {
    useJarvisStore.setState({
      activeTab: 'command',
      machineState: 'Offline',
      activeRequestId: null,
      canceledRequestIds: [],
      lastSeq: 0,
      staleEventsRejected: 0,
      pendingApproval: null,
      memories: [],
      knowledgeRoots: [],
      tasks: [],
      expenseSummaries: [],
      workflows: [],
      lastTurnReply: '',
      lastTurnReplyAt: 0,
      eventLog: [],
    })
  })

  it('advances Event Cursor seq and opens native R2 <dialog> on approval.required SSE event', async () => {
    render(<App />)
    await waitFor(() => expect(useJarvisStore.getState().capabilities).not.toBeNull())

    const accepted = useJarvisStore.getState().applySequencedEvent({
      schema_version: 1,
      event_id: 'ev-r2-1',
      seq: 7,
      request_id: null,
      correlation_id: 'corr-r2-1',
      type: 'approval.required',
      occurred_at: '2026-11-27T10:00:00Z',
      payload: {
        approval_id: 'appr-sse-1',
        action_run_id: 'run-sse-1',
        tool_id: 'fs.file.move',
        tool_version: 1,
        bound_hash: 'd'.repeat(64),
        nonce: 'e'.repeat(32),
        expires_at: new Date(Date.now() + 60_000).toISOString(),
        summary: 'SSE-delivered R2 approval challenge',
      },
    })

    expect(accepted).toBe(true)
    expect(useJarvisStore.getState().lastSeq).toBe(7)
    expect(await screen.findByRole('button', { name: /Tolak \(Esc\)/i })).toBeInTheDocument()
  })

  it('passes real user-entered expense category instead of hardcoded general (DEF-18)', () => {
    const spy = vi.fn()
    render(
      <PersonalLifePanel
        tasks={[]}
        expenseSummaries={[]}
        onCreateTask={vi.fn()}
        onToggleTaskDone={vi.fn()}
        onRecordExpense={spy}
      />,
    )

    fireEvent.change(screen.getByLabelText(/Kategori pengeluaran/i), {
      target: { value: 'transportasi' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Catat Pengeluaran Lokal/i }))

    expect(spy).toHaveBeenCalledWith({
      amountMinor: 50000,
      currencyIso: 'IDR',
      kind: 'expense',
      category: 'transportasi',
    })
  })

  it('replaces optimistic memory ID with persisted Core UUID and hydrates user data cleanly', () => {
    const store = useJarvisStore.getState()
    store.addMemory({
      id: 'mem-temp-1',
      kind: 'fact',
      content: 'Preferensi lokal',
      is_encrypted: false,
      sensitivity: 'normal',
      source_ref: 'local_owner',
      status: 'active',
      revision: 1,
      created_at: '2026-11-27T10:00:00Z',
      updated_at: '2026-11-27T10:00:00Z',
    })

    store.replaceMemoryId('mem-temp-1', {
      id: '550e8400-e29b-41d4-a716-446655440000',
      kind: 'fact',
      content: 'Preferensi lokal',
      is_encrypted: false,
      sensitivity: 'normal',
      source_ref: 'local_owner',
      status: 'active',
      revision: 1,
      created_at: '2026-11-27T10:00:00Z',
      updated_at: '2026-11-27T10:00:00Z',
    })

    expect(useJarvisStore.getState().memories[0]?.id).toBe(
      '550e8400-e29b-41d4-a716-446655440000',
    )

    useJarvisStore.getState().hydratePersistedData({
      tasks: [{ id: 'task-real-1', title: 'Hydrated Task', status: 'open', revision: 1 }],
    })
    expect(useJarvisStore.getState().tasks[0]?.title).toBe('Hydrated Task')
  })

  it('displays truthful Stage G4 workflow execution status without fake execution claims', () => {
    render(<WorkflowsPanel workflows={[]} onCreateSampleWorkflow={vi.fn()} />)
    expect(screen.getByText(/Stage G4/i)).toBeInTheDocument()
  })
})
