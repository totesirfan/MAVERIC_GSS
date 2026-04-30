import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PowerBalanceCard } from './PowerBalanceCard'
import type { EpsFieldName } from '../types'

const coherentT = {
  V_BUS: 1000,
  I_BUS: 1000,
  V_BAT: 1000,
  I_BAT: 1000,
  P3V3: 1000,
  P5V0: 1000,
  POUT1: 1000,
} satisfies Partial<Record<EpsFieldName, number>>

describe('PowerBalanceCard', () => {
  it('renders load-derived battery input when raw battery current under-reports same-HK loads', () => {
    render(<PowerBalanceCard
      field_t={coherentT}
      fields={{
        V_BUS: 0, I_BUS: 0,
        V_BAT: 7.5, I_BAT: -0.016,
        P3V3: 0.70, I3V3: 0.212,
        P5V0: 0.40, I5V0: 0.080,
        POUT1: 0.37, IOUT1: 0.050,
      }}
    />)

    expect(screen.getByText('BAT 1.47 W')).toBeTruthy()
    expect(screen.getByText('load-derived · raw 0.12 W')).toBeTruthy()
    expect(screen.getByTitle('Load-derived battery source; V_BAT × -I_BAT = 0.12 W').textContent).toBe('1.47 W')
  })

  it('does not balance stale HK loads against newer beacon bus fields', () => {
    render(<PowerBalanceCard
      field_t={{
        V_BUS: 3000,
        I_BUS: 3000,
        V_BAT: 3000,
        I_BAT: 3000,
        P3V3: 1000,
        P5V0: 1000,
        POUT1: 1000,
      }}
      fields={{
        V_BUS: 0, I_BUS: 0,
        V_BAT: 7.5, I_BAT: -0.016,
        P3V3: 0.70,
        P5V0: 0.40,
        POUT1: 0.37,
      }}
    />)

    expect(screen.getByText('HK stale')).toBeTruthy()
    expect(screen.getByText('loads not balanced')).toBeTruthy()
    expect(screen.getByText('BAT 0.12 W')).toBeTruthy()
    expect(screen.getByText('stale')).toBeTruthy()
  })
})
