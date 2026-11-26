import type { FpsTarget, VisualQualityTier } from './contracts'

export interface VisualPacingInput {
  readonly qualityTier: VisualQualityTier
  readonly fpsTarget: FpsTarget
  readonly detectedRefreshHz: number
  readonly onBattery: boolean
  readonly underInferencePressure: boolean
  readonly isDocumentHidden: boolean
  readonly prefersReducedMotion: boolean
}

export interface FramePacingPlan {
  readonly shouldAnimate: boolean
  readonly effectiveFps: number
  readonly targetPeriodMs: number
  readonly vsyncHarmonicThresholdMs: number
  readonly dprCap: number
  readonly enableParticles: boolean
}

export interface FrameTelemetrySnapshot {
  readonly renderedFrames: number
  readonly measuredFps: number
  readonly p50Ms: number
  readonly p95Ms: number
  readonly droppedFrames: number
}

/**
 * Compute adaptive visual pacing obeying DEC-010, DEC-030, and BR-UX-02:
 * - Zero continuous animation frames when hidden or Reduced Motion is active.
 * - Uses VSync-harmonic threshold `targetMs - 0.55 * estimatedVsyncMs` so high-Hz
 *   displays (e.g., 144Hz/200Hz) align cleanly to integer VSync multiples without
 *   missing a tick and slipping down a band.
 */
export function computeFramePacingPlan(input: VisualPacingInput): FramePacingPlan {
  const safeHz = Number.isFinite(input.detectedRefreshHz) && input.detectedRefreshHz >= 24
    ? input.detectedRefreshHz
    : 60

  if (
    input.isDocumentHidden ||
    input.prefersReducedMotion ||
    input.qualityTier === 'reduced_motion'
  ) {
    return {
      shouldAnimate: false,
      effectiveFps: 0,
      targetPeriodMs: Number.POSITIVE_INFINITY,
      vsyncHarmonicThresholdMs: Number.POSITIVE_INFINITY,
      dprCap: 1,
      enableParticles: false,
    }
  }

  let effectiveFps: number
  if (input.fpsTarget === 'native') {
    effectiveFps = safeHz
  } else if (input.fpsTarget === '30') {
    effectiveFps = 30
  } else if (input.fpsTarget === '60') {
    effectiveFps = 60
  } else if (input.fpsTarget === '120') {
    effectiveFps = Math.min(120, safeHz)
  } else {
    // Auto adapts dynamically to display Hz, power state, and live inference pressure
    if (input.onBattery || input.qualityTier === 'lite') {
      effectiveFps = 30
    } else if (input.underInferencePressure) {
      effectiveFps = Math.min(60, safeHz)
    } else {
      effectiveFps = Math.min(120, safeHz)
    }
  }

  const estimatedVsyncMs = 1000 / safeHz
  const targetPeriodMs = 1000 / effectiveFps
  const vsyncHarmonicThresholdMs =
    input.fpsTarget === 'native'
      ? 0
      : Math.max(0, targetPeriodMs - 0.55 * estimatedVsyncMs)

  const dprCap = input.qualityTier === 'cinematic' ? 2 : input.qualityTier === 'balanced' ? 1.5 : 1
  const enableParticles = input.qualityTier === 'cinematic' && !input.onBattery

  return {
    shouldAnimate: true,
    effectiveFps,
    targetPeriodMs,
    vsyncHarmonicThresholdMs,
    dprCap,
    enableParticles,
  }
}

export function shouldRenderAtTimestamp(
  nowMs: number,
  lastRenderMs: number,
  plan: FramePacingPlan,
): boolean {
  if (!plan.shouldAnimate) {
    return false
  }
  if (lastRenderMs <= 0) {
    return true
  }
  if (plan.vsyncHarmonicThresholdMs === 0) {
    return true
  }
  return nowMs - lastRenderMs >= plan.vsyncHarmonicThresholdMs
}

export class FrameTelemetryTracker {
  private readonly deltas: number[] = []
  private readonly maxSamples: number
  private dropped = 0
  private lastTs = 0

  constructor(maxSamples = 120) {
    this.maxSamples = maxSamples
  }

  recordFrame(timestampMs: number, expectedPeriodMs: number): void {
    if (this.lastTs > 0) {
      const delta = timestampMs - this.lastTs
      if (delta > 0) {
        this.deltas.push(delta)
        if (this.deltas.length > this.maxSamples) {
          this.deltas.shift()
        }
        if (Number.isFinite(expectedPeriodMs) && delta > expectedPeriodMs * 1.75) {
          this.dropped += 1
        }
      }
    }
    this.lastTs = timestampMs
  }

  reset(): void {
    this.deltas.length = 0
    this.dropped = 0
    this.lastTs = 0
  }

  snapshot(): FrameTelemetrySnapshot {
    if (this.deltas.length === 0) {
      return {
        renderedFrames: 0,
        measuredFps: 0,
        p50Ms: 0,
        p95Ms: 0,
        droppedFrames: this.dropped,
      }
    }
    const sorted = [...this.deltas].sort((a, b) => a - b)
    const p50 = sorted[Math.floor(sorted.length * 0.5)] ?? 0
    const p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] ?? 0
    const mean = sorted.reduce((acc, v) => acc + v, 0) / sorted.length
    return {
      renderedFrames: this.deltas.length,
      measuredFps: mean > 0 ? Math.round((1000 / mean) * 10) / 10 : 0,
      p50Ms: Math.round(p50 * 10) / 10,
      p95Ms: Math.round(p95 * 10) / 10,
      droppedFrames: this.dropped,
    }
  }
}
