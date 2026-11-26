import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { App } from '../App'
import { useJarvisStore } from '../store/jarvisStore'

describe('Phase 5 (R3): Ecosystem, On-Demand Camera, HA Safety Bans, Remote Gateway & Preference Proposals', () => {
  beforeEach(() => {
    useJarvisStore.setState({
      activeTab: 'ecosystem',
      privacy: {
        micMode: 'muted',
        cameraActive: false,
        offlineMode: true,
        executionZone: 'direct_offline',
      },
      haEntities: [
        {
          entity_id: 'light.desk_lamp',
          domain: 'light',
          friendly_name: 'Lampu Meja Kerja',
          allowed_actions: ['read_state', 'turn_on', 'turn_off'],
          enabled: true,
        },
      ],
      remoteGatewayEnabled: false,
      remoteHostAvailable: true,
      remoteDevices: [
        {
          id: 'dev-sample-mobile',
          label: 'Paired Mobile Client (Scoped)',
          scopes: ['remote.status.read', 'remote.chat.send', 'remote.reminder.read'],
          revoked_at: null,
        },
      ],
      preferenceProposals: [
        {
          id: 'prop-verbosity-brief',
          preference_key: 'persona.verbosity',
          proposed_value: 'brief',
          rationale: 'Terdeteksi 3 koreksi eksplisit lokal agar jawaban lebih ringkas.',
          evidence_count: 3,
          status: 'pending',
        },
      ],
      activePersonaVerbosity: 'standard',
    })
  })

  it('toggles on-demand camera indicator explicitly and clears on stop', () => {
    render(<App />)
    expect(screen.getByTestId('badge-cam').textContent).toContain('CAM: OFF')

    fireEvent.click(screen.getByRole('button', { name: /Izinkan Snapshot Sesi Ini/i }))
    expect(screen.getByTestId('badge-cam').textContent).toContain('CAM: ON-DEMAND')

    fireEvent.click(screen.getByRole('button', { name: /Hentikan Kamera Segera/i }))
    expect(screen.getByTestId('badge-cam').textContent).toContain('CAM: OFF')
  })

  it('blocks R3 safety-critical Home Assistant entities and allows safe light entities', () => {
    render(<App />)
    const entityInput = screen.getByLabelText('Entity ID Home Assistant')
    const nameInput = screen.getByLabelText('Nama ramah entitas')

    fireEvent.change(entityInput, { target: { value: 'lock.front_door' } })
    fireEvent.change(nameInput, { target: { value: 'Pintu Depan' } })
    fireEvent.click(screen.getByRole('button', { name: /Tambah Allowlist/i }))
    expect(screen.getByText(/Ditolak \(R3\)/i)).toBeTruthy()

    fireEvent.change(entityInput, { target: { value: 'light.reading_lamp' } })
    fireEvent.change(nameInput, { target: { value: 'Lampu Baca' } })
    fireEvent.click(screen.getByRole('button', { name: /Tambah Allowlist/i }))
    expect(screen.getAllByText(/light\.reading_lamp/i).length).toBeGreaterThan(0)
  })

  it('shows host unreachable without silent queue and revokes remote devices instantaneously', () => {
    render(<App />)
    expect(screen.getByTestId('remote-host-badge').textContent).toContain('DISABLED BY DEFAULT')

    fireEvent.click(screen.getByRole('button', { name: /Simulasikan Host Tidur\/Offline/i }))
    expect(screen.getByTestId('remote-host-badge').textContent).toContain('HOST UNREACHABLE')

    fireEvent.click(screen.getByRole('button', { name: /Cabut Seketika/i }))
    expect(screen.getByText('REVOKED')).toBeTruthy()
  })

  it('leaves active verbosity unchanged when rejecting an adaptive preference proposal', () => {
    render(<App />)
    expect(screen.getByTestId('active-verbosity-badge').textContent).toContain('standard')

    fireEvent.click(screen.getByRole('button', { name: /^Tolak$/i }))
    expect(screen.getByTestId('active-verbosity-badge').textContent).toContain('standard')
    expect(screen.getByText(/rejected/i)).toBeTruthy()
  })
})
