import fieldsManifest from './fields.json'

type FieldEntry = {
  name: string
  unit: string
  digits: number
  group: string
  raw_scale: number
  signed_display?: boolean
  polarity_inverted?: boolean
  vout_index?: number
  burn_index?: number
  solar_index?: number
  subsystem?: string
}

type DerivedEntry = { name: string; unit: string; digits: number; formula: string }

type GroupEntry = { id: string; label: string; count: number }

export type EpsFieldName =
  | 'I_BUS' | 'I_BAT' | 'V_BUS' | 'V_AC1' | 'V_AC2' | 'V_BAT' | 'V_SYS'
  | 'TS_ADC' | 'T_DIE'
  | 'V3V3' | 'I3V3' | 'P3V3' | 'V5V0' | 'I5V0' | 'P5V0'
  | 'VOUT1' | 'IOUT1' | 'POUT1'
  | 'VOUT2' | 'IOUT2' | 'POUT2'
  | 'VOUT3' | 'IOUT3' | 'POUT3'
  | 'VOUT4' | 'IOUT4' | 'POUT4'
  | 'VOUT5' | 'IOUT5' | 'POUT5'
  | 'VOUT6' | 'IOUT6' | 'POUT6'
  | 'VBRN1' | 'IBRN1' | 'PBRN1'
  | 'VBRN2' | 'IBRN2' | 'PBRN2'
  | 'VSIN1' | 'ISIN1' | 'PSIN1'
  | 'VSIN2' | 'ISIN2' | 'PSIN2'
  | 'VSIN3' | 'ISIN3' | 'PSIN3'

export type EpsFields = { [K in EpsFieldName]: number }

/** Sparse per-field map — any subset of EpsFieldName keys may be present.
 *
 * The EPS domain is populated by multiple sources (eps_hk covers all
 * 48 fields atomically; tlm_beacon covers a 7-field subset). Two
 * sources → two cadences → different per-field ages. Consumers must
 * treat each field's freshness independently, not as an atomic
 * "snapshot age".
 */
export type EpsFieldMap = Partial<Record<EpsFieldName, number>>

export type AlarmLevel = 'ok' | 'caution' | 'danger' | 'unknown'

export type ChargeDir = 'charge' | 'discharge' | 'idle'

export type SourceId = 'V_AC1' | 'V_AC2' | 'VSIN1' | 'VSIN2' | 'VSIN3' | 'BAT'

export type GroupId = 'all' | 'bus' | 'solar' | 'thermal' | 'rails' | 'vout' | 'burn'

export interface EpsFieldDef {
  name: EpsFieldName
  unit: string
  digits: number
  group: GroupId
  signedDisplay: boolean
  polarityInverted: boolean
  subsystem?: string
}

export interface EpsGroupDef {
  id: GroupId
  label: string
  count: number
}

const rawFields = (fieldsManifest as { fields: FieldEntry[] }).fields
const rawGroups = (fieldsManifest as { groups: GroupEntry[] }).groups
const rawDerived = (fieldsManifest as { derived: DerivedEntry[] }).derived

export const FIELD_DEFS: readonly EpsFieldDef[] = rawFields.map((f) => ({
  name: f.name as EpsFieldName,
  unit: f.unit,
  digits: f.digits,
  group: f.group as GroupId,
  signedDisplay: !!f.signed_display,
  polarityInverted: !!f.polarity_inverted,
  subsystem: f.subsystem,
}))

export const FIELD_DEF_BY_NAME: Readonly<Record<EpsFieldName, EpsFieldDef>> = (() => {
  const out: Partial<Record<EpsFieldName, EpsFieldDef>> = {}
  for (const d of FIELD_DEFS) out[d.name] = d
  return out as Record<EpsFieldName, EpsFieldDef>
})()

export const GROUP_DEFS: readonly EpsGroupDef[] = rawGroups.map((g) => ({
  id: g.id as GroupId,
  label: g.label,
  count: g.count,
}))

export type DerivedName = 'P_BUS' | 'P_AC' | 'P_IN' | 'P_OUT' | 'EFFICIENCY'

export const DERIVED_NAMES: readonly DerivedName[] = rawDerived.map((d) => d.name as DerivedName)
