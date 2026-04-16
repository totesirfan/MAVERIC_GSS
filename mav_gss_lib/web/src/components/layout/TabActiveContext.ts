/**
 * Tab-active context — provides `isActive: boolean` to components inside a
 * TabViewport slot. Any component that registers global listeners (keydown,
 * pointer, etc.) while mounted in a hidden-but-kept-alive tab subtree MUST
 * gate those registrations on `useTabActive()`.
 *
 * Default value is `true`, so components outside any TabActiveProvider
 * (e.g. shell chrome) are always considered active.
 */
import { createContext, useContext } from 'react'

const TabActiveContext = createContext<boolean>(true)

export function useTabActive(): boolean {
  return useContext(TabActiveContext)
}

export const TabActiveProvider = TabActiveContext.Provider
