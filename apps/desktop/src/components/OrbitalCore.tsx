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
  readonly voiceAmplitude?: number
  readonly onBattery?: boolean
  readonly onTelemetryUpdate?: (snapshot: FrameTelemetrySnapshot) => void
}

interface StatePalette {
  readonly stroke: string
  readonly secondary: string
  readonly haloRgba: string
  readonly label: string
}

const STATE_PALETTE: Readonly<Record<MachineState, StatePalette>> = {
  Startup: {
    stroke: '#57dfff',
    secondary: '#7dd3fc',
    haloRgba: 'rgba(87, 223, 255, 0.24)',
    label: 'BOOT SEQUENCE',
  },
  Idle: {
    stroke: '#57dfff',
    secondary: '#5eead4',
    haloRgba: 'rgba(87, 223, 255, 0.20)',
    label: 'STANDBY CALIBRATED',
  },
  Listening: {
    stroke: '#57dfff',
    secondary: '#93f0ff',
    haloRgba: 'rgba(87, 223, 255, 0.34)',
    label: 'ACOUSTIC CAPTURE',
  },
  Transcribing: {
    stroke: '#67e8f9',
    secondary: '#5eead4',
    haloRgba: 'rgba(103, 232, 249, 0.28)',
    label: 'WHISPER DECODE',
  },
  Thinking: {
    stroke: '#57dfff',
    secondary: '#a5f3fc',
    haloRgba: 'rgba(87, 223, 255, 0.32)',
    label: 'NEURAL INFERENCE',
  },
  Executing: {
    stroke: '#5eead4',
    secondary: '#57dfff',
    haloRgba: 'rgba(94, 234, 212, 0.32)',
    label: 'TOOL EXECUTION',
  },
  Approval: {
    stroke: '#ffbe69',
    secondary: '#fde68a',
    haloRgba: 'rgba(255, 190, 105, 0.32)',
    label: 'R2 GATE LOCKED',
  },
  Speaking: {
    stroke: '#57dfff',
    secondary: '#5eead4',
    haloRgba: 'rgba(87, 223, 255, 0.32)',
    label: 'VOICE SYNTHESIS',
  },
  Success: {
    stroke: '#5eead4',
    secondary: '#99f6e4',
    haloRgba: 'rgba(94, 234, 212, 0.28)',
    label: 'VERIFIED COMPLETE',
  },
  Error: {
    stroke: '#ff737c',
    secondary: '#fda4af',
    haloRgba: 'rgba(255, 115, 124, 0.30)',
    label: 'FAULT CONTAINED',
  },
  Muted: {
    stroke: '#7dd3fc',
    secondary: '#64748b',
    haloRgba: 'rgba(125, 211, 252, 0.14)',
    label: 'MIC HARDWARE MUTED',
  },
  Offline: {
    stroke: '#7dd3fc',
    secondary: '#5eead4',
    haloRgba: 'rgba(125, 211, 252, 0.18)',
    label: 'LOCAL AIR-GAPPED',
  },
}

interface OrbitalParticle {
  angle: number
  radius: number
  speed: number
  size: number
  alpha: number
  eccentricity: number
}

const COMPASS_TICKS: ReadonlyArray<{
  readonly x1: number
  readonly y1: number
  readonly x2: number
  readonly y2: number
  readonly major: boolean
}> = Array.from({ length: 72 }, (_, idx) => {
  const rad = ((idx * 5 - 90) * Math.PI) / 180
  const major = idx % 6 === 0
  const rInner = major ? 115 : 119
  const rOuter = 124
  return {
    x1: 140 + Math.cos(rad) * rInner,
    y1: 140 + Math.sin(rad) * rInner,
    x2: 140 + Math.cos(rad) * rOuter,
    y2: 140 + Math.sin(rad) * rOuter,
    major,
  }
})

const EQUALIZER_BARS = 24

function createParticlePool(count: number): OrbitalParticle[] {
  // Deterministic golden-angle seeded orbital particle pool (zero per-frame heap allocation)
  return Array.from({ length: count }, (_, i) => ({
    angle: (i * 2.399963229728653) % (Math.PI * 2),
    radius: 78 + (i % 5) * 11,
    speed: (i % 2 === 0 ? 1 : -1) * (0.22 + (i % 4) * 0.08),
    size: i % 3 === 0 ? 2.1 : 1.35,
    alpha: 0.25 + (i % 4) * 0.14,
    eccentricity: 0.94 + (i % 3) * 0.03,
  }))
}

export function OrbitalCore({
  machineState,
  qualityTier,
  fpsTarget,
  detectedRefreshHz,
  voiceAmplitude = 0,
  onBattery = false,
  onTelemetryUpdate,
}: OrbitalCoreProps) {
  // Imperative DOM & Canvas 2D refs -> ZERO React setState calls per animation frame (B21)
  const angleDegRef = useRef(0)
  const phaseSecRef = useRef(0)
  const ampRef = useRef(0)
  ampRef.current = Math.max(0, Math.min(1, voiceAmplitude))

  const outerRingRef = useRef<SVGGElement | null>(null)
  const midRingRef = useRef<SVGGElement | null>(null)
  const innerRingRef = useRef<SVGGElement | null>(null)
  const sweepArcRef = useRef<SVGGElement | null>(null)
  const eqLineRefs = useRef<Array<SVGLineElement | null>>([])
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const particlesRef = useRef<OrbitalParticle[]>(createParticlePool(24))

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

  const palette = STATE_PALETTE[machineState]

  useEffect(() => {
    trackerRef.current.reset()
    lastRenderMsRef.current = 0

    const canUseCanvas2d =
      typeof navigator === 'undefined' || !/jsdom/i.test(navigator.userAgent)

    const clearCanvas = () => {
      if (!canUseCanvas2d) return
      const cv = canvasRef.current
      if (!cv || typeof cv.getContext !== 'function') return
      const ctx = cv.getContext('2d')
      if (ctx) ctx.clearRect(0, 0, cv.width, cv.height)
    }

    if (!plan.shouldAnimate) {
      clearCanvas()
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
        phaseSecRef.current += dtSec

        const speedDegPerSec =
          machineState === 'Thinking' || machineState === 'Executing'
            ? 46
            : machineState === 'Listening' || machineState === 'Speaking'
              ? 30
              : 14
        angleDegRef.current = (angleDegRef.current + dtSec * speedDegPerSec) % 360
        const deg = angleDegRef.current

        outerRingRef.current?.setAttribute('transform', `rotate(${deg.toFixed(2)} 140 140)`)
        midRingRef.current?.setAttribute('transform', `rotate(${(-deg * 0.72).toFixed(2)} 140 140)`)
        innerRingRef.current?.setAttribute('transform', `rotate(${(deg * 1.35).toFixed(2)} 140 140)`)
        sweepArcRef.current?.setAttribute('transform', `rotate(${(deg * 1.9).toFixed(2)} 140 140)`)

        // Imperative radial acoustic equalizer bars (harmonic ambient idle + live voice amplitude)
        const liveAmp = ampRef.current
        const tPhase = phaseSecRef.current
        for (let i = 0; i < EQUALIZER_BARS; i += 1) {
          const line = eqLineRefs.current[i]
          if (!line) continue
          const theta = ((i * (360 / EQUALIZER_BARS) - 90) * Math.PI) / 180
          const harmonic = 0.5 + 0.5 * Math.sin(tPhase * 3.6 + i * 0.78)
          const baseLen = 4.5 + harmonic * 3.5
          const voiceBoost = liveAmp * (11 + harmonic * 15)
          const rStart = 49
          const rEnd = rStart + baseLen + voiceBoost
          line.setAttribute('x2', (140 + Math.cos(theta) * rEnd).toFixed(1))
          line.setAttribute('y2', (140 + Math.sin(theta) * rEnd).toFixed(1))
        }

        // Pooled Canvas 2D orbital micro-particles (only on balanced/cinematic tiers)
        if (plan.enableParticles && canUseCanvas2d) {
          const cv = canvasRef.current
          if (cv && typeof cv.getContext === 'function') {
            const ctx = cv.getContext('2d')
            if (ctx) {
              ctx.clearRect(0, 0, cv.width, cv.height)
              const cx = cv.width / 2
              const cy = cv.height / 2
              const speedMult =
                machineState === 'Thinking' || machineState === 'Executing'
                  ? 1.85
                  : 1 + liveAmp * 1.2
              ctx.fillStyle = palette.stroke
              for (const p of particlesRef.current) {
                p.angle += p.speed * speedMult * dtSec
                const px = cx + Math.cos(p.angle) * p.radius
                const py = cy + Math.sin(p.angle) * p.radius * p.eccentricity
                ctx.globalAlpha = Math.min(0.85, p.alpha + liveAmp * 0.25)
                ctx.beginPath()
                ctx.arc(px, py, p.size, 0, Math.PI * 2)
                ctx.fill()
              }
              ctx.globalAlpha = 1
            }
          }
        }

        frameCounter += 1
        if (frameCounter % 20 === 0) {
          onTelemetryUpdate?.(trackerRef.current.snapshot())
        }
      }
      rafId = window.requestAnimationFrame(tick)
    }

    rafId = window.requestAnimationFrame(tick)
    return () => {
      window.cancelAnimationFrame(rafId)
      clearCanvas()
    }
  }, [plan, machineState, palette.stroke, onTelemetryUpdate])

  const clampedAmp = Math.max(0, Math.min(1, voiceAmplitude))
  const reactiveRadius = 48 + clampedAmp * 24

  return (
    <div
      className="jarvis-panel jarvis-hud-frame relative flex flex-col items-center justify-between overflow-hidden rounded-2xl p-5"
      data-testid="orbital-core"
      data-machine-state={machineState}
      data-animating={plan.shouldAnimate ? 'true' : 'false'}
    >
      {/* State-keyed radial atmospheric bloom behind the Orbital Core */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 transition-opacity duration-500"
        style={{
          background: `radial-gradient(circle at 50% 44%, ${palette.haloRgba} 0%, transparent 66%)`,
        }}
      />

      {/* Top instrument micro-header */}
      <div className="relative z-10 flex w-full items-center justify-between text-[10px] tracking-[0.14em]">
        <span className="font-mono-tabular inline-flex items-center gap-1.5" style={{ color: 'var(--text-secondary)' }}>
          <span
            className={plan.shouldAnimate ? 'jarvis-live-dot h-1.5 w-1.5 rounded-full' : 'h-1.5 w-1.5 rounded-full'}
            style={{ backgroundColor: palette.stroke }}
          />
          ARC-CORE // 01
        </span>
        <span className="font-mono-tabular" style={{ color: palette.stroke }}>
          {palette.label}
        </span>
      </div>

      {/* Layered Procedural Orbital Stage (Canvas 2D Particles + Calibrated Vector Core) */}
      <div className="relative z-10 my-2 flex h-64 w-64 items-center justify-center">
        <canvas
          ref={canvasRef}
          width={280}
          height={280}
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 h-full w-full"
        />

        <svg
          viewBox="0 0 280 280"
          className="relative h-64 w-64 select-none"
          role="img"
          aria-label={`Orbital Precision Core — status ${machineState}`}
        >
          <defs>
            <radialGradient id="jarvis-iris-grad" cx="50%" cy="46%" r="54%">
              <stop offset="0%" stopColor={palette.stroke} stopOpacity="0.22" />
              <stop offset="65%" stopColor="#091426" stopOpacity="0.92" />
              <stop offset="100%" stopColor="#050b16" stopOpacity="0.98" />
            </radialGradient>
            <linearGradient id="jarvis-sweep-grad" x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={palette.stroke} stopOpacity="0" />
              <stop offset="65%" stopColor={palette.stroke} stopOpacity="0.45" />
              <stop offset="100%" stopColor={palette.secondary} stopOpacity="0.95" />
            </linearGradient>
            <filter id="jarvis-orbital-glow" x="-30%" y="-30%" width="160%" height="160%">
              <feGaussianBlur stdDeviation="2.6" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* 72-tick calibrated azimuth compass ring */}
          <g aria-hidden="true">
            <circle
              cx="140"
              cy="140"
              r="125"
              fill="none"
              stroke="rgba(126, 173, 226, 0.15)"
              strokeWidth="1"
            />
            {COMPASS_TICKS.map((tick, idx) => (
              <line
                key={idx}
                x1={tick.x1.toFixed(1)}
                y1={tick.y1.toFixed(1)}
                x2={tick.x2.toFixed(1)}
                y2={tick.y2.toFixed(1)}
                stroke={tick.major ? palette.stroke : 'rgba(126, 173, 226, 0.28)'}
                strokeOpacity={tick.major ? '0.62' : '0.45'}
                strokeWidth={tick.major ? '1.35' : '0.8'}
              />
            ))}
            <text x="140" y="10" textAnchor="middle" fill="#8499b5" fontSize="7" className="font-mono-tabular">
              000
            </text>
            <text x="272" y="142.5" textAnchor="end" fill="#8499b5" fontSize="7" className="font-mono-tabular">
              090
            </text>
            <text x="140" y="276" textAnchor="middle" fill="#8499b5" fontSize="7" className="font-mono-tabular">
              180
            </text>
            <text x="8" y="142.5" textAnchor="start" fill="#8499b5" fontSize="7" className="font-mono-tabular">
              270
            </text>
          </g>

          {/* Outer luminous segmented stator ring (imperative rotation) */}
          <g ref={outerRingRef} transform="rotate(0 140 140)" filter="url(#jarvis-orbital-glow)">
            <circle
              cx="140"
              cy="140"
              r="104"
              fill="none"
              stroke={palette.stroke}
              strokeWidth="2.4"
              strokeDasharray="78 24 18 24 44 24"
              strokeLinecap="round"
            />
            {plan.enableParticles && (
              <>
                <circle cx="244" cy="140" r="3.2" fill={palette.stroke} />
                <circle cx="36" cy="140" r="2.4" fill={palette.secondary} opacity="0.82" />
                <circle cx="140" cy="36" r="2" fill={palette.stroke} opacity="0.65" />
              </>
            )}
          </g>

          {/* Fast radar-sweep arc accent */}
          <g ref={sweepArcRef} transform="rotate(0 140 140)">
            <path
              d="M 140 44 A 96 96 0 0 1 214 79"
              fill="none"
              stroke="url(#jarvis-sweep-grad)"
              strokeWidth="2.2"
              strokeLinecap="round"
            />
          </g>

          {/* Midground counter-rotating precision telemetry ring */}
          <g ref={midRingRef} transform="rotate(0 140 140)">
            <circle
              cx="140"
              cy="140"
              r="84"
              fill="none"
              stroke={palette.secondary}
              strokeWidth="1.5"
              strokeOpacity="0.58"
              strokeDasharray="24 12 6 12"
            />
            <circle cx="140" cy="56" r="2.1" fill={palette.secondary} opacity="0.75" />
            <circle cx="140" cy="224" r="2.1" fill={palette.secondary} opacity="0.75" />
          </g>

          {/* Inner gyroscope stabilizer brackets */}
          <g ref={innerRingRef} transform="rotate(0 140 140)">
            <circle
              cx="140"
              cy="140"
              r="68"
              fill="none"
              stroke={palette.stroke}
              strokeWidth="1.15"
              strokeOpacity="0.4"
              strokeDasharray="12 22"
            />
          </g>

          {/* 24-Bar Radial Acoustic Equalizer (FR-UX-02 — RAM envelope only, zero PCM stored) */}
          <g aria-hidden="true">
            {Array.from({ length: EQUALIZER_BARS }, (_, i) => {
              const theta = ((i * (360 / EQUALIZER_BARS) - 90) * Math.PI) / 180
              const rStart = 49
              const rEnd = 54.5
              return (
                <line
                  key={i}
                  ref={(el) => {
                    eqLineRefs.current[i] = el
                  }}
                  x1={(140 + Math.cos(theta) * rStart).toFixed(1)}
                  y1={(140 + Math.sin(theta) * rStart).toFixed(1)}
                  x2={(140 + Math.cos(theta) * rEnd).toFixed(1)}
                  y2={(140 + Math.sin(theta) * rEnd).toFixed(1)}
                  stroke={palette.stroke}
                  strokeOpacity={0.34 + clampedAmp * 0.56}
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              )
            })}
          </g>

          {/* Voice-reactive acoustic pulse membrane */}
          <circle
            cx="140"
            cy="140"
            r={reactiveRadius.toFixed(1)}
            fill="none"
            stroke={palette.stroke}
            strokeWidth={(1.2 + clampedAmp * 2.8).toFixed(1)}
            strokeOpacity={(0.2 + clampedAmp * 0.68).toFixed(2)}
          />

          {/* Core Iris */}
          <motion.circle
            cx="140"
            cy="140"
            r="43"
            fill="url(#jarvis-iris-grad)"
            stroke={palette.stroke}
            strokeWidth="2"
            filter="url(#jarvis-orbital-glow)"
            initial={false}
            animate={{
              scale:
                plan.shouldAnimate && (machineState === 'Thinking' || clampedAmp > 0.08)
                  ? 1 + Math.min(0.12, 0.035 + clampedAmp * 0.085)
                  : 1,
            }}
            transition={{ duration: 0.14 }}
          />
          <circle
            cx="140"
            cy="140"
            r="36"
            fill="none"
            stroke={palette.stroke}
            strokeOpacity="0.28"
            strokeWidth="0.9"
            strokeDasharray="4 4"
          />

          <text
            x="140"
            y="136"
            textAnchor="middle"
            fill="#eaf3ff"
            fontSize="12"
            fontWeight="700"
            letterSpacing="0.18em"
          >
            J.A.R.V.I.S.
          </text>
          <text
            x="140"
            y="153"
            textAnchor="middle"
            fill={palette.stroke}
            fontSize="10"
            fontWeight="600"
            letterSpacing="0.08em"
            className="font-mono-tabular"
          >
            {machineState.toUpperCase()}
          </text>
        </svg>
      </div>

      {/* Bottom calibrated telemetry bar + acoustic level meter */}
      <div className="relative z-10 w-full space-y-2.5 pt-1">
        <div className="space-y-1">
          <div className="font-mono-tabular flex items-center justify-between text-[10px]" style={{ color: 'var(--text-muted)' }}>
            <span>ACOUSTIC ENVELOPE</span>
            <span style={{ color: palette.stroke }}>{Math.round(clampedAmp * 100)}%</span>
          </div>
          <div
            className="h-1.5 w-full overflow-hidden rounded-full"
            style={{ backgroundColor: 'rgba(126, 173, 226, 0.14)' }}
          >
            <div
              className="h-full rounded-full transition-[width] duration-100"
              style={{
                width: `${Math.max(4, Math.round(clampedAmp * 100))}%`,
                background: `linear-gradient(90deg, ${palette.stroke}, ${palette.secondary})`,
              }}
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-center gap-2 text-[11px]">
          <span
            className="font-mono-tabular rounded-md border px-2.5 py-0.5"
            style={{
              borderColor: 'var(--border-subtle)',
              backgroundColor: 'rgba(6, 11, 20, 0.65)',
              color: 'var(--text-secondary)',
            }}
          >
            TIER: {qualityTier.toUpperCase()}
          </span>
          <span
            className="font-mono-tabular rounded-md border px-2.5 py-0.5"
            style={{
              borderColor: 'var(--border-subtle)',
              backgroundColor: 'rgba(6, 11, 20, 0.65)',
              color: plan.shouldAnimate ? 'var(--status-ok)' : 'var(--text-muted)',
            }}
          >
            PACING: {plan.shouldAnimate ? `${Math.round(plan.effectiveFps)} FPS` : 'PAUSED (0 FPS)'}
          </span>
        </div>
      </div>
    </div>
  )
}
