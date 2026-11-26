import { useEffect, useMemo, useRef, useState } from 'react'
import { motion } from 'motion/react'
import type { FpsTarget, MachineState, VisualQualityTier } from '../lib/contracts'
import {
  computeFramePacingPlan,
  FrameTelemetryTracker,
  shouldRenderAtTimestamp,
  type FrameTelemetrySnapshot,
} from '../lib/visualEngine'

interface OrbitalCoreProps {
  readonly machineState: MachineState
  readonly qualityTier: VisualQualityTier
  readonly fpsTarget: FpsTarget
  readonly detectedRefreshHz: number
  readonly onBattery?: boolean
  readonly onTelemetryUpdate?: (snapshot: FrameTelemetrySnapshot) => void
}

const STATE_RING_COLOR: Readonly<Record<MachineState, string>> = {
  Startup: '#57dfff',
  Idle: '#57dfff',
  Listening: '#57dfff',
  Transcribing: '#57dfff',
  Thinking: '#57dfff',
  Executing: '#5eead4',
  Approval: '#ffbe69',
  Speaking: '#57dfff',
  Success: '#5eead4',
  Error: '#ff737c',
  Muted: '#7f93ac',
  Offline: '#a9b9cc',
}

export function OrbitalCore({
  machineState,
  qualityTier,
  fpsTarget,
  detectedRefreshHz,
  onBattery = false,
  onTelemetryUpdate,
}: OrbitalCoreProps) {
  const [angleDeg, setAngleDeg] = useState(0)
  const [isHidden, setIsHidden] = useState(
    typeof document !== 'undefined' ? document.visibilityState === 'hidden' : false,
  )
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false,
  )
  const trackerRef = useRef(new FrameTelemetryTracker(90))
  const lastRenderMsRef = useRef(0)

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return
    }
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const onChange = (ev: MediaQueryListEvent) => setPrefersReducedMotion(ev.matches)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [])

  useEffect(() => {
    if (typeof document === 'undefined') {
      return
    }
    const onVis = () => setIsHidden(document.visibilityState === 'hidden')
    document.addEventListener('visibilitychange', onVis)
    return () => document.removeEventListener('visibilitychange', onVis)
  }, [])

  const plan = useMemo(
    () =>
      computeFramePacingPlan({
        qualityTier,
        fpsTarget,
        detectedRefreshHz,
        onBattery,
        underInferencePressure: machineState === 'Thinking' || machineState === 'Executing',
        isDocumentHidden: isHidden,
        prefersReducedMotion,
      }),
    [qualityTier, fpsTarget, detectedRefreshHz, onBattery, machineState, isHidden, prefersReducedMotion],
  )

  useEffect(() => {
    trackerRef.current.reset()
    lastRenderMsRef.current = 0
    if (!plan.shouldAnimate) {
      onTelemetryUpdate?.(trackerRef.current.snapshot())
      return
    }

    let rafId = 0
    let frameCounter = 0

    const tick = (ts: number) => {
      if (shouldRenderAtTimestamp(ts, lastRenderMsRef.current, plan)) {
        const dtSec = lastRenderMsRef.current > 0 ? Math.min(0.1, (ts - lastRenderMsRef.current) / 1000) : 0
        lastRenderMsRef.current = ts
        trackerRef.current.recordFrame(ts, plan.targetPeriodMs)
        const speedDegPerSec = machineState === 'Thinking' || machineState === 'Executing' ? 42 : 16
        setAngleDeg((prev) => (prev + dtSec * speedDegPerSec) % 360)
        frameCounter += 1
        if (frameCounter % 20 === 0) {
          onTelemetryUpdate?.(trackerRef.current.snapshot())
        }
      }
      rafId = window.requestAnimationFrame(tick)
    }

    rafId = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(rafId)
  }, [plan, machineState, onTelemetryUpdate])

  const ringStroke = STATE_RING_COLOR[machineState]

  return (
    <div
      className="relative flex flex-col items-center justify-center rounded-xl border p-6"
      style={{
        backgroundColor: 'var(--surface-panel)',
        borderColor: 'var(--border-subtle)',
      }}
      data-testid="orbital-core"
      data-machine-state={machineState}
      data-animating={plan.shouldAnimate ? 'true' : 'false'}
    >
      <svg
        viewBox="0 0 240 240"
        className="h-52 w-52"
        role="img"
        aria-label={`Orbital Precision Core — status ${machineState}`}
      >
        {/* Outer reference ring */}
        <circle
          cx="120"
          cy="120"
          r="102"
          fill="none"
          stroke="#233349"
          strokeWidth="1.5"
        />

        {/* Calibrated rotating precision ring */}
        <g transform={`rotate(${angleDeg.toFixed(2)} 120 120)`}>
          <circle
            cx="120"
            cy="120"
            r="86"
            fill="none"
            stroke={ringStroke}
            strokeWidth="2.5"
            strokeDasharray="64 26 14 26"
            strokeLinecap="round"
          />
          {plan.enableParticles && (
            <>
              <circle cx="206" cy="120" r="3" fill={ringStroke} />
              <circle cx="34" cy="120" r="2.2" fill={ringStroke} opacity="0.65" />
            </>
          )}
        </g>

        {/* Counter-rotating inner telemetry ring */}
        <g transform={`rotate(${(-angleDeg * 0.65).toFixed(2)} 120 120)`}>
          <circle
            cx="120"
            cy="120"
            r="64"
            fill="none"
            stroke={ringStroke}
            strokeWidth="1.5"
            strokeOpacity="0.55"
            strokeDasharray="20 14"
          />
        </g>

        {/* Core iris */}
        <motion.circle
          cx="120"
          cy="120"
          r="34"
          fill="#0b1524"
          stroke={ringStroke}
          strokeWidth="2"
          initial={false}
          animate={{ scale: plan.shouldAnimate && machineState === 'Thinking' ? 1.04 : 1 }}
          transition={{ duration: 0.25 }}
        />

        <text
          x="120"
          y="117"
          textAnchor="middle"
          fill="#e6f1ff"
          fontSize="11"
          fontWeight="600"
          letterSpacing="0.14em"
        >
          J.A.R.V.I.S.
        </text>
        <text
          x="120"
          y="134"
          textAnchor="middle"
          fill={ringStroke}
          fontSize="10"
          className="font-mono-tabular"
        >
          {machineState.toUpperCase()}
        </text>
      </svg>

      <div className="mt-3 flex flex-wrap items-center justify-center gap-2 text-xs">
        <span
          className="font-mono-tabular rounded-md border px-2 py-0.5"
          style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-secondary)' }}
        >
          TIER: {qualityTier.toUpperCase()}
        </span>
        <span
          className="font-mono-tabular rounded-md border px-2 py-0.5"
          style={{ borderColor: 'var(--border-subtle)', color: 'var(--text-secondary)' }}
        >
          PACING: {plan.shouldAnimate ? `${Math.round(plan.effectiveFps)} FPS` : 'PAUSED (0 FPS)'}
        </span>
      </div>
    </div>
  )
}
