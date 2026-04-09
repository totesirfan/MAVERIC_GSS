import { useState, useEffect, useRef } from 'react'

const RECEIVE_TIMEOUT_MS = 2000

export function useReceivingDetection(lastPktNum: number) {
  const [receiving, setReceiving] = useState(false)
  const prevLastNum = useRef(-1)
  const receiveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (lastPktNum > prevLastNum.current) {
      setReceiving(true)
      if (receiveTimer.current) clearTimeout(receiveTimer.current)
      receiveTimer.current = setTimeout(() => setReceiving(false), RECEIVE_TIMEOUT_MS)
    }
    prevLastNum.current = lastPktNum
  }, [lastPktNum])
  /* eslint-enable react-hooks/set-state-in-effect */

  useEffect(() => () => {
    if (receiveTimer.current) clearTimeout(receiveTimer.current)
  }, [])

  return receiving
}
