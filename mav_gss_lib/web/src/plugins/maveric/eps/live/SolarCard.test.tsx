import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SolarCard } from './SolarCard'

describe('SolarCard', () => {
  it('renders three rows and "0 / 3" rollup when all panels idle', () => {
    render(<SolarCard fields={{
      VSIN1: 0, ISIN1: 0, PSIN1: 0,
      VSIN2: 0, ISIN2: 0, PSIN2: 0,
      VSIN3: 0, ISIN3: 0, PSIN3: 0,
    }} />)
    expect(screen.getAllByText(/^IDLE$/)).toHaveLength(3)
    expect(screen.getByText('0 / 3')).toBeTruthy()
  })

  it('renders "3 / 3" rollup when all panels generating', () => {
    render(<SolarCard fields={{
      VSIN1: 3.4, ISIN1: 0.44, PSIN1: 1.5,
      VSIN2: 3.4, ISIN2: 0.44, PSIN2: 1.5,
      VSIN3: 3.3, ISIN3: 0.15, PSIN3: 0.5,
    }} />)
    expect(screen.getAllByText(/^GEN$/)).toHaveLength(3)
    expect(screen.getByText('3 / 3')).toBeTruthy()
  })

  it('renders "FAULT 2 / 3" rollup when one panel is DEAD', () => {
    render(<SolarCard fields={{
      VSIN1: 3.4, ISIN1: 0.44, PSIN1: 1.5,
      VSIN2: 3.4, ISIN2: 0.44, PSIN2: 1.5,
      VSIN3: 0.02, ISIN3: -0.003, PSIN3: 0.005,
    }} />)
    expect(screen.getAllByText(/^GEN$/)).toHaveLength(2)
    expect(screen.getByText('DEAD')).toBeTruthy()
    expect(screen.getByText('FAULT 2 / 3')).toBeTruthy()
  })
})
