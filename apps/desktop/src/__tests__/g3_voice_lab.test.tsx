import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RuntimeVisualPanel } from '../components/FoundationPanels'

describe('Stage G3 (B11/B12) Voice Lab UI Controls & Diagnostics', () => {
  it('renders live Voice Lab diagnostics, allows device/rate selection, and submits corrected transcript replay', () => {
    const onSelectDevices = vi.fn()
    const onRateChange = vi.fn()
    const onReplay = vi.fn()

    render(
      <RuntimeVisualPanel
        ownershipMode="managed_local"
        qualityTier="balanced"
        fpsTarget="auto"
        detectedRefreshHz={120}
        telemetry={{ renderedFrames: 60, measuredFps: 60, p50Ms: 16, p95Ms: 17, droppedFrames: 0 }}
        voiceDiagnostics={{
          schema_version: 1,
          diagnostics: {
            mode: 'wake',
            phase: 'standby_wake',
            selected_input_device: 'USB Desk Mic',
            selected_output_device: 'Studio Headphones',
            output_form_factor: 'headphones',
            echo_guard_enabled: true,
            echo_guard_reason: 'Isolated headphone/headset output detected; full voice barge-in enabled.',
            voice_barge_in_allowed: true,
            live_rms: 0.012,
            noise_floor_rms: 0.004,
            clipping_events: 0,
            queue_overflow_drops: 0,
            utterance_drops: 0,
            playback_generation: 2,
            vad_engine: 'silero-vad',
            wake_engine: 'openwakeword-hey-jarvis',
            stt_model: 'faster-whisper-small',
            stt_language_mode: 'multilingual_auto',
            speech_rate: 1.0,
            installed_piper_voices: { id: 'piper-id-news' },
            last_confidence: 0.92,
            last_detected_language: 'id',
            recent_traces: [],
          },
          endpoints: [
            { id: 'mic-usb', name: 'USB Desk Mic', direction: 'input', is_default: true, form_factor: 'microphone' },
            { id: 'hp-1', name: 'Studio Headphones', direction: 'output', is_default: true, form_factor: 'headphones' },
          ],
        }}
        onOwnershipChange={vi.fn()}
        onQualityChange={vi.fn()}
        onFpsChange={vi.fn()}
        onSelectAudioDevices={onSelectDevices}
        onSpeechRateChange={onRateChange}
        onReplayTranscript={onReplay}
      />,
    )

    expect(screen.getByText(/Voice Lab & Diagnostik Audio/i)).toBeInTheDocument()
    expect(screen.getByText(/Headset Barge-In/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '1.15x' }))
    expect(onRateChange).toHaveBeenCalledWith(1.15)

    fireEvent.change(screen.getByLabelText(/Pilih speaker atau headset Voice Lab/i), {
      target: { value: 'hp-1' },
    })
    expect(onSelectDevices).toHaveBeenCalledWith(null, 'hp-1')

    fireEvent.change(screen.getByLabelText(/Koreksi dan putar ulang transkrip suara/i), {
      target: { value: 'Buka kalkulator.' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Putar Ulang Transkrip/i }))
    expect(onReplay).toHaveBeenCalledWith('Buka kalkulator.')
  })
})
