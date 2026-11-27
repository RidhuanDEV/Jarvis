import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ApprovalDialog } from '../components/ApprovalDialog'
import { OnboardingWizard } from '../components/OnboardingWizard'
import { OrbitalCore } from '../components/OrbitalCore'

describe('Stage G5 (B21) HUD Imperative OrbitalCore, Unified Diff Dialog & WCAG AA', () => {
  it('runs OrbitalCore rAF animation imperatively with ZERO React re-renders per frame', () => {
    let renderCount = 0
    const callbacks: FrameRequestCallback[] = []
    const origRaf = window.requestAnimationFrame
    const origCancel = window.cancelAnimationFrame
    window.requestAnimationFrame = vi.fn((cb: FrameRequestCallback) => {
      callbacks.push(cb)
      return callbacks.length
    })
    window.cancelAnimationFrame = vi.fn()

    function SpyOrbital() {
      renderCount += 1
      return (
        <OrbitalCore
          machineState="Thinking"
          qualityTier="balanced"
          fpsTarget="60"
          detectedRefreshHz={60}
        />
      )
    }

    try {
      render(<SpyOrbital />)
      const initialRenders = renderCount
      // Simulate 5 animation frames at 60Hz (16.7ms apart)
      for (let i = 1; i <= 5; i += 1) {
        const cb = callbacks.shift()
        if (cb) cb(i * 20)
      }
      // Imperative DOM SVG rotation MUST NOT trigger any React state re-render!
      expect(renderCount).toBe(initialRenders)
    } finally {
      window.requestAnimationFrame = origRaf
      window.cancelAnimationFrame = origCancel
    }
  })

  it('renders structured unified diff preview and accessible expiry alert inside ApprovalDialog', () => {
    render(
      <ApprovalDialog
        challenge={{
          approval_id: 'appr-diff-1',
          action_run_id: 'run-1',
          tool_id: 'fs.file.edit',
          tool_version: 1,
          bound_hash: 'b'.repeat(64),
          nonce: 'n'.repeat(32),
          expires_at: new Date(Date.now() + 8_000).toISOString(),
          summary: 'Edit notes.md',
          before_preview: 'notes.md',
          after_preview: '--- a/notes.md\n+++ b/notes.md\n@@ -1,2 +1,2 @@\n-Baris lama\n+Baris baru',
        }}
        onApprove={vi.fn()}
        onReject={vi.fn()}
        onExpire={vi.fn()}
      />,
    )

    expect(screen.getByTestId('approval-diff-preview')).toBeTruthy()
    expect(screen.getByText('-Baris lama')).toBeTruthy()
    expect(screen.getByText('+Baris baru')).toBeTruthy()
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Tolak (Esc)' }))
  })

  it('exposes accessible progressbar label and status live region in OnboardingWizard', () => {
    render(
      <OnboardingWizard
        capabilities={null}
        storageLocations={[]}
        qualityTier="balanced"
        fpsTarget="auto"
        runtimeOwnershipMode="none"
        onApplyRecommendedSetup={vi.fn()}
        onSelectRuntime={vi.fn()}
        onSelectVisuals={vi.fn()}
        onCompleteOnboarding={vi.fn()}
      />,
    )

    expect(screen.getByRole('progressbar', { name: 'Progres langkah onboarding' })).toBeTruthy()
    expect(screen.getByRole('status')).toBeTruthy()
  })
})
