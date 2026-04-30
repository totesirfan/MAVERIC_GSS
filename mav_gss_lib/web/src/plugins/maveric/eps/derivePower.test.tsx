import { describe, expect, it } from 'vitest'
import {
  batteryChargePower,
  batteryDischargePower,
  batteryInputPower,
  batterySourceActive,
  deriveEpsBoardPower,
  derivePAC,
  efficiency,
  measuredLoadPower,
} from './derive'
import type { EpsFields } from './types'

describe('EPS power balance derivation', () => {
  it('does not add battery charge on top of P_BUS when deriving AC power', () => {
    const got = derivePAC({
      V_BUS: 9.0, I_BUS: 1.0,
      PSIN1: 0, PSIN2: 0, PSIN3: 0,
      V_BAT: 8.0, I_BAT: 0.5,
    } as Partial<EpsFields>)

    expect(got).toBeCloseTo(9.0, 3)
  })

  it('subtracts battery charging from the EPS board residual', () => {
    const got = deriveEpsBoardPower({
      V_BUS: 10, I_BUS: 1,
      V_BAT: 8, I_BAT: 0.5,
      P3V3: 2,
      P5V0: 1,
    } as Partial<EpsFields>)

    expect(got).toBeCloseTo(3, 3)
  })

  it('ignores negative load noise and impossible battery power', () => {
    expect(measuredLoadPower({
      P3V3: 0.5,
      P5V0: 0.2,
      POUT1: 1.0,
      POUT2: -0.2,
      PBRN1: -0.1,
    } as Partial<EpsFields>)).toBeCloseTo(1.7, 3)

    expect(batteryChargePower({ V_BAT: -8, I_BAT: 0.5 } as Partial<EpsFields>)).toBe(0)
    expect(batteryDischargePower({ V_BAT: -7.5, I_BAT: -0.4 } as Partial<EpsFields>)).toBe(0)
  })

  it('uses measured HK loads for battery-only input when VBAT current under-reports', () => {
    const fields = {
      V_BUS: 0, I_BUS: 0,
      V_BAT: 7.5, I_BAT: -0.016,
      P3V3: 0.70,
      P5V0: 0.40,
      POUT1: 0.37,
    } as Partial<EpsFields>

    const got = batteryInputPower(fields, measuredLoadPower(fields))

    expect(got.measuredWatts).toBeCloseTo(0.12, 3)
    expect(got.watts).toBeCloseTo(1.47, 3)
    expect(got.derivedFromLoads).toBe(true)
  })

  it('keeps raw battery discharge power when VBUS reports bus demand', () => {
    const fields = {
      V_BUS: 8, I_BUS: 0.2,
      V_BAT: 7.5, I_BAT: -0.016,
      P3V3: 0.70,
      P5V0: 0.40,
      POUT1: 0.37,
    } as Partial<EpsFields>

    const got = batteryInputPower(fields, measuredLoadPower(fields))

    expect(got.watts).toBeCloseTo(0.12, 3)
    expect(got.derivedFromLoads).toBe(false)
  })

  it('classifies battery-only source when I_BAT is near zero but loads are real', () => {
    const fields = {
      V_AC1: 0, V_AC2: 0,
      V_BUS: 0.03, I_BUS: 0.006,
      V_BAT: 8.197, I_BAT: 0,
      V_SYS: 8.15,
      P3V3: 0.58,
      P5V0: 0.31,
      POUT1: 0.59,
      PSIN1: 0, PSIN2: 0, PSIN3: 0,
    } as Partial<EpsFields>

    expect(batterySourceActive(fields)).toBe(true)
  })

  it('does not show efficiency when HK loads exceed measured bus power', () => {
    const got = efficiency({
      V_BUS: 8.9, I_BUS: 0.14,
      P3V3: 0.62,
      P5V0: 0.32,
      POUT1: 0.55,
      POUT2: 0.35,
    } as Partial<EpsFields>, null)

    expect(got).toBeNull()
  })
})
