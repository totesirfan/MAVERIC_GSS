import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BurnCard } from './BurnCard'

const base = {
  VBRN1: 0, IBRN1: 0, PBRN1: 0,
  VBRN2: 0, IBRN2: 0, PBRN2: 0,
  latched: {},
  onAcknowledge: () => {},
}

describe('BurnCard', () => {
  it('shows SAFE rollup + SAFE badges when both cells quiet', () => {
    render(<BurnCard {...base} />)
    // SAFE appears 3× total (rollup lbl + 2 cell badges). Use getAllByText
    // because getByText would throw on multiple matches.
    expect(screen.getAllByText(/^SAFE$/)).toHaveLength(3)
  })

  it('shows FAULT rollup + ALARM badge when VBRN1 is hot', () => {
    render(<BurnCard {...base} VBRN1={1.2} IBRN1={0.4} PBRN1={0.48} />)
    // FAULT (rollup) and ALARM (VBRN1 cell) each appear exactly once here.
    expect(screen.getByText('FAULT')).toBeTruthy()
    expect(screen.getByText('ALARM')).toBeTruthy()
  })

  it('shows LATCH rollup + LATCH badge + ACK button when latched', () => {
    render(<BurnCard {...base} latched={{ VBRN1: 123456 }} />)
    // LATCH appears 2× (rollup lbl + VBRN1 cell badge). Use getAllByText.
    expect(screen.getAllByText(/^LATCH$/)).toHaveLength(2)
    const ackBtn = screen.getByRole('button', { name: /Acknowledge VBRN1 latch/i })
    expect(ackBtn).toBeTruthy()
  })

  it('invokes onAcknowledge with field id when ACK clicked', () => {
    const onAck = vi.fn()
    render(<BurnCard {...base} latched={{ VBRN2: 123456 }} onAcknowledge={onAck} />)
    fireEvent.click(screen.getByRole('button', { name: /Acknowledge VBRN2 latch/i }))
    expect(onAck).toHaveBeenCalledWith('VBRN2')
  })
})
