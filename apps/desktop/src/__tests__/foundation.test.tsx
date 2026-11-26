import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, beforeEach } from 'vitest'
import App from '../App'
import {
  computeFramePacingPlan,
  FrameTelemetryTracker,
  shouldRenderAtTimestamp,
} from '../lib/visualEngine'
import { useJarvisStore } from '../store/jarvisStore'

describe('AdaptiveVisualEngine (DEC-010 & DEC-030)', () => {
  it('uses VSync-harmonic threshold on 200 Hz display so 60 FPS lands on 15ms instead of slipping to 20ms', () => {
    const plan = computeFramePacingPlan({
      qualityTier: 'balanced',
      fpsTarget: '60',
      detectedRefreshHz: 200,
      onBattery: false,
      underInferencePressure: false,
      isDocumentHidden: false,
      prefersReducedMotion: false,
    })

    expect(plan.shouldAnimate).toBe(true)
    expect(plan.effectiveFps).toBe(60)
    // 16.667ms - 0.55 * 5ms = 13.917ms -> fires on 3rd 5ms VSync tick (15ms), NOT 20ms!
    expect(shouldRenderAtTimestamp(10, 0, plan)).toBe(true) // first frame
    expect(shouldRenderAtTimestamp(20, 10, plan)).toBe(false) // +10ms < 13.9ms
    expect(shouldRenderAtTimestamp(25, 10, plan)).toBe(true) // +15ms >= 13.9ms!
  })

  it('renders 0 continuous animation frames in ReducedMotion or when document is hidden', () => {
    const reduced = computeFramePacingPlan({
      qualityTier: 'reduced_motion',
      fpsTarget: 'native',
      detectedRefreshHz: 200,
      onBattery: false,
      underInferencePressure: false,
      isDocumentHidden: false,
      prefersReducedMotion: false,
    })
    expect(reduced.shouldAnimate).toBe(false)
    expect(shouldRenderAtTimestamp(100, 0, reduced)).toBe(false)

    const hidden = computeFramePacingPlan({
      qualityTier: 'cinematic',
      fpsTarget: 'native',
      detectedRefreshHz: 144,
      onBattery: false,
      underInferencePressure: false,
      isDocumentHidden: true,
      prefersReducedMotion: false,
    })
    expect(hidden.shouldAnimate).toBe(false)
    expect(shouldRenderAtTimestamp(100, 0, hidden)).toBe(false)
  })

  it('tracks real p50/p95 frame telemetry accurately', () => {
    const tracker = new FrameTelemetryTracker(20)
    tracker.recordFrame(100, 16.67)
    tracker.recordFrame(115, 16.67)
    tracker.recordFrame(130, 16.67)
    tracker.recordFrame(145, 16.67)
    const snap = tracker.snapshot()
    expect(snap.renderedFrames).toBe(3)
    expect(snap.p50Ms).toBe(15)
    expect(snap.droppedFrames).toBe(0)
  })
})

describe('Monotonic (request_id, seq) reducer anti-ghosting (10-UX-DESIGN §5)', () => {
  beforeEach(() => {
    useJarvisStore.setState({
      machineState: 'Offline',
      activeRequestId: null,
      canceledRequestIds: [],
      lastSeq: 0,
      staleEventsRejected: 0,
      pendingApproval: null,
      eventLog: [],
    })
  })

  it('rejects out-of-order seq and late events from canceled requests', () => {
    const store = useJarvisStore.getState()
    store.startRequest('req-1')

    const accepted1 = useJarvisStore.getState().applySequencedEvent({
      schema_version: 1,
      event_id: 'ev-1',
      seq: 1,
      request_id: 'req-1',
      correlation_id: 'corr-1',
      type: 'request.state_changed',
      occurred_at: '2026-11-26T12:00:00Z',
      payload: { state: 'Executing' },
    })
    expect(accepted1).toBe(true)
    expect(useJarvisStore.getState().machineState).toBe('Executing')

    // Duplicate/older seq MUST be rejected
    const dup = useJarvisStore.getState().applySequencedEvent({
      schema_version: 1,
      event_id: 'ev-dup',
      seq: 1,
      request_id: 'req-1',
      correlation_id: 'corr-1',
      type: 'request.state_changed',
      occurred_at: '2026-11-26T12:00:01Z',
      payload: { state: 'Success' },
    })
    expect(dup).toBe(false)
    expect(useJarvisStore.getState().machineState).toBe('Executing')
    expect(useJarvisStore.getState().staleEventsRejected).toBe(1)

    // Cancel req-1 -> subsequent late event for req-1 with higher seq MUST be rejected!
    useJarvisStore.getState().cancelActiveRequest()
    expect(useJarvisStore.getState().machineState).toBe('Offline')

    const ghost = useJarvisStore.getState().applySequencedEvent({
      schema_version: 1,
      event_id: 'ev-ghost',
      seq: 2,
      request_id: 'req-1',
      correlation_id: 'corr-1',
      type: 'request.state_changed',
      occurred_at: '2026-11-26T12:00:02Z',
      payload: { state: 'Success' },
    })
    expect(ghost).toBe(false)
    expect(useJarvisStore.getState().machineState).toBe('Offline')
    expect(useJarvisStore.getState().staleEventsRejected).toBe(2)
  })
})

describe('Orbital Precision Shell & Native <dialog> R2 Approval Safety', () => {
  beforeEach(() => {
    useJarvisStore.setState({
      activeTab: 'command',
      machineState: 'Offline',
      pendingApproval: null,
      privacy: {
        micMode: 'muted',
        cameraActive: false,
        offlineMode: true,
        executionZone: 'direct_offline',
      },
    })
  })

  it('displays explicit privacy badges and focuses Tolak (Esc) first inside native R2 <dialog>', async () => {
    render(<App />)

    await waitFor(() => {
      expect(useJarvisStore.getState().capabilities).not.toBeNull()
    })

    expect(screen.getByText('MIC: MUTED')).toBeInTheDocument()
    expect(screen.getByText('CAM: OFF')).toBeInTheDocument()
    expect(screen.getByTestId('badge-network')).toHaveTextContent('OFFLINE')

    const previewBtn = screen.getByRole('button', { name: /Pratinjau Dialog R2/i })
    fireEvent.click(previewBtn)

    const rejectBtn = await screen.findByRole('button', { name: /Tolak \(Esc\)/i })
    expect(rejectBtn).toBeInTheDocument()
    await waitFor(() => {
      expect(document.activeElement).toBe(rejectBtn)
    })

    fireEvent.click(rejectBtn)
    await waitFor(() => {
      expect(useJarvisStore.getState().pendingApproval).toBeNull()
    })
  })
})
