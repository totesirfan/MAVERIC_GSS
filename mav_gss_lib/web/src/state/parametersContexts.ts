import { createContext } from 'react'

export interface ParameterSpec {
  name: string                  // "<group>.<key>"
  group: string | null
  key: string
  type: string
  unit: string
  description: string
  enum: Record<string, number> | null
  tags: Record<string, unknown>
}

export interface ParameterEntry {
  v: unknown
  t: number
  display_only?: boolean
}

export interface ContainerFreshness {
  last_ms: number | null
  expected_period_ms: number | null
}

type GroupedState = Record<string, Record<string, ParameterEntry>>

export interface ParametersContextValue {
  grouped: GroupedState
  specByName: Map<string, ParameterSpec>
  specsByGroup: Record<string, ParameterSpec[]>
  timestamps: Record<string, number>
  freshness: Record<string, ContainerFreshness>
}

export const ParametersContext = createContext<ParametersContextValue | null>(null)
