import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { EcosystemPanel } from '../components/EcosystemPanels'

describe('Stage G7 (B26) Opt-In Ecosystem Capability Packs UI', () => {
  it('renders offline degradation badge, per-connector consent status, and handles revocation', () => {
    const onRevokeConnector = vi.fn()

    render(
      <EcosystemPanel
        cameraActive={false}
        haEntities={[]}
        remoteGatewayEnabled={false}
        remoteHostAvailable={true}
        remoteDevices={[]}
        preferenceProposals={[]}
        activePersonaVerbosity="standard"
        offlineMode={true}
        ecosystemConnectors={[
          {
            id: 'gcal-ro',
            kind: 'oauth_calendar',
            display_name: 'Calendar Read-Only (PKCE)',
            endpoint_url: 'https://oauth.example.org/api',
            allowed_scopes: ['calendar.readonly'],
            consent_acknowledged: true,
            enabled: true,
            revoked_at: null,
          },
          {
            id: 'web_search_default',
            kind: 'web_search',
            display_name: 'SearXNG Local',
            endpoint_url: 'http://127.0.0.1:8080/search',
            allowed_scopes: ['web.search.readonly'],
            consent_acknowledged: false,
            enabled: false,
            revoked_at: '2026-11-27T12:00:00Z',
          },
        ]}
        onSetCameraActive={vi.fn()}
        onAddHaEntity={vi.fn(() => true)}
        onToggleRemoteGateway={vi.fn()}
        onToggleRemoteHostAvailable={vi.fn()}
        onRevokeRemoteDevice={vi.fn()}
        onDecideProposal={vi.fn()}
        onRevokeEcosystemConnector={onRevokeConnector}
      />,
    )

    expect(screen.getByTestId('ecosystem-offline-badge').textContent).toContain(
      'OFFLINE DEGRADATION ACTIVE',
    )
    expect(screen.getByText('Calendar Read-Only (PKCE)')).toBeTruthy()
    expect(screen.getByText('CONSENTED · READ-ONLY')).toBeTruthy()
    expect(screen.getByText('REVOKED')).toBeTruthy()

    const revokeButtons = screen.getAllByRole('button', { name: 'Cabut Konektor' })
    expect(revokeButtons).toHaveLength(2)
    const [firstBtn, secondBtn] = revokeButtons
    if (!firstBtn || !secondBtn) {
      throw new Error('Expected two revoke connector buttons')
    }
    expect(firstBtn).not.toBeDisabled()
    expect(secondBtn).toBeDisabled()

    fireEvent.click(firstBtn)
    expect(onRevokeConnector).toHaveBeenCalledWith('gcal-ro')
  })
})
