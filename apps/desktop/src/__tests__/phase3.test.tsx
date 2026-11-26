import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import App from '../App'
import { useJarvisStore } from '../store/jarvisStore'

describe('Phase 3 UI: 10-Step Onboarding, Command Turn, Memory Vault & Reminders', () => {
  beforeEach(() => {
    useJarvisStore.setState({
      activeTab: 'command',
      machineState: 'Offline',
      pendingApproval: null,
      memories: [],
      reminders: [],
      onboardingCompleted: false,
      lastTurnReply: '',
      privacy: {
        micMode: 'muted',
        cameraActive: false,
        offlineMode: true,
        executionZone: 'direct_offline',
      },
    })
  })

  it('completes Guided 10-Step Onboarding offline via 1-Click Recommended Setup with 0 GB download', async () => {
    render(<App />)
    await waitFor(() => expect(useJarvisStore.getState().capabilities).not.toBeNull())

    fireEvent.click(screen.getByRole('button', { name: /Onboarding \(10 Steps\)/i }))
    expect(screen.getByText(/LANGKAH 1 DARI 10/i)).toBeInTheDocument()

    // 1-Click Recommended Setup jumps straight to step 10 offline readiness
    fireEvent.click(screen.getByRole('button', { name: /1-Click Recommended Setup/i }))
    expect(screen.getByText(/Uji Kesiapan Offline Lulus/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /Selesaikan Onboarding/i }))
    expect(useJarvisStore.getState().onboardingCompleted).toBe(true)
    expect(useJarvisStore.getState().activeTab).toBe('command')
  })

  it('routes deterministic Command Turn offline and triggers native R2 <dialog> for file move', async () => {
    render(<App />)
    await waitFor(() => expect(useJarvisStore.getState().capabilities).not.toBeNull())

    const input = screen.getByLabelText(/Perintah teks lokal/i)
    fireEvent.change(input, { target: { value: 'jam berapa' } })
    fireEvent.click(screen.getByRole('button', { name: /Kirim/i }))

    await waitFor(() => {
      expect(screen.getAllByText(/0 panggilan LLM — Direct Mode/i).length).toBeGreaterThanOrEqual(1)
    })

    // R2 file move triggers native <dialog> with Tolak (Esc) focused
    fireEvent.change(input, { target: { value: 'pindahkan file a.txt ke b.txt' } })
    fireEvent.click(screen.getByRole('button', { name: /Kirim/i }))

    const rejectBtn = await screen.findByRole('button', { name: /Tolak \(Esc\)/i })
    await waitFor(() => expect(document.activeElement).toBe(rejectBtn))
    fireEvent.click(rejectBtn)
  })

  it('creates encrypted AES-256-GCM memory and schedules IANA reminder', async () => {
    render(<App />)
    await waitFor(() => expect(useJarvisStore.getState().capabilities).not.toBeNull())

    // Memory Vault
    fireEvent.click(screen.getByRole('button', { name: /Memory Vault/i }))
    fireEvent.change(screen.getByLabelText(/Isi memori baru/i), {
      target: { value: 'Kode brankas pribadi disimpan terenkripsi' },
    })
    fireEvent.change(screen.getByLabelText(/Sensitivitas memori/i), {
      target: { value: 'sensitive' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Simpan Memori/i }))

    expect(screen.getByText('AES-256-GCM')).toBeInTheDocument()
    expect(screen.getByText(/Kode brankas pribadi/i)).toBeInTheDocument()

    // Reminders
    fireEvent.click(screen.getByRole('button', { name: /Reminders/i }))
    fireEvent.change(screen.getByLabelText(/Judul pengingat baru/i), {
      target: { value: 'Istirahat mata 5 menit' },
    })
    fireEvent.click(screen.getByRole('button', { name: /Jadwalkan/i }))
    expect(screen.getByText('Istirahat mata 5 menit')).toBeInTheDocument()
  })
})
