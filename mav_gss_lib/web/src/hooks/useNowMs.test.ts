import { renderHook, act } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useNowMs } from './useNowMs'

describe('useNowMs', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-24T00:00:00Z'))
  })
  afterEach(() => { vi.useRealTimers() })

  it('returns the current wall time on mount', () => {
    const { result } = renderHook(() => useNowMs())
    expect(result.current).toBe(Date.now())
  })

  it('updates approximately every second', () => {
    const { result } = renderHook(() => useNowMs())
    const start = result.current
    act(() => { vi.advanceTimersByTime(1001) })
    expect(result.current).toBeGreaterThanOrEqual(start + 1000)
  })
})
