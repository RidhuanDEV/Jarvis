import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { EcosystemPanel } from '../components/EcosystemPanels'

describe('Stage G6 (B23) MCP Manager UI & Global Kill Switch', () => {
  it('renders MCP server provenance, blocks quarantined re-enable, and fires global kill switch', () => {
    const onToggle = vi.fn()
    const onKill = vi.fn()

    render(
      <EcosystemPanel
        cameraActive={false}
        haEntities={[]}
        remoteGatewayEnabled={false}
        remoteHostAvailable={true}
        remoteDevices={[]}
        preferenceProposals={[]}
        activePersonaVerbosity="standard"
        mcpServers={[
          {
            id: 'local-notes',
            display_name: 'Local Notes Read-Only',
            version: '1.0.0',
            transport: 'stdio',
            trust_tier: 'reviewed_readonly',
            data_destination: 'local_only',
            allowed_scopes: ['read_only'],
            enabled: true,
            quarantined: false,
            quarantine_reason: null,
            schema_pin_sha256: 'a'.repeat(64),
            pinned_tools: [
              {
                tool_name: 'read_note',
                namespaced_tool_id: 'mcp.local-notes.read_note',
                read_only: true,
                approved: true,
              },
            ],
          },
          {
            id: 'rugpull-srv',
            display_name: 'Compromised Server',
            version: '1.0.1',
            transport: 'stdio',
            trust_tier: 'untrusted',
            data_destination: 'local_only',
            allowed_scopes: ['read_only'],
            enabled: false,
            quarantined: true,
            quarantine_reason: 'SHA-256 schema drift detected',
            schema_pin_sha256: 'b'.repeat(64),
            pinned_tools: [],
          },
        ]}
        onSetCameraActive={vi.fn()}
        onAddHaEntity={vi.fn(() => true)}
        onToggleRemoteGateway={vi.fn()}
        onToggleRemoteHostAvailable={vi.fn()}
        onRevokeRemoteDevice={vi.fn()}
        onDecideProposal={vi.fn()}
        onToggleMcpServer={onToggle}
        onTriggerMcpKillSwitch={onKill}
      />,
    )

    expect(screen.getByText('Local Notes Read-Only')).toBeTruthy()
    expect(screen.getByText('QUARANTINED')).toBeTruthy()
    expect(screen.getByRole('alert')).toBeTruthy()

    // Quarantined server enable button MUST be disabled (strict typing: no `as` cast)
    expect(screen.getByRole('button', { name: 'Aktifkan' })).toBeDisabled()

    // Healthy server disable button triggers callback
    fireEvent.click(screen.getByRole('button', { name: 'Nonaktifkan' }))
    expect(onToggle).toHaveBeenCalledWith('local-notes', false)

    // Global MCP Kill Switch triggers cleanly
    fireEvent.click(screen.getByRole('button', { name: /MCP Kill Switch/i }))
    expect(onKill).toHaveBeenCalledTimes(1)
  })
})
