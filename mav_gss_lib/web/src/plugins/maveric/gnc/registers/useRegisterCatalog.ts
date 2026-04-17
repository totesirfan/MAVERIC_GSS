import { useEffect, useState } from 'react'
import type { CatalogEntry } from '../types'

/** Fetch the full register catalog from the backend once per mount.
 *  Metadata doesn't change during a session, so no re-fetch is needed
 *  outside of initial load and explicit page reload. */
export function useRegisterCatalog(): CatalogEntry[] {
  const [catalog, setCatalog] = useState<CatalogEntry[]>([])

  useEffect(() => {
    const ac = new AbortController()
    fetch('/api/plugins/gnc/catalog', { signal: ac.signal })
      .then((r) => (r.ok ? r.json() : []))
      .then((data: CatalogEntry[]) => {
        if (Array.isArray(data)) setCatalog(data)
      })
      .catch(() => {
        /* backend offline — table stays empty, operator sees the
         * "no catalog" message from the component itself */
      })
    return () => ac.abort()
  }, [])

  return catalog
}
