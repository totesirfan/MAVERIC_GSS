/**
 * Mission runtime — app-root provider infrastructure.
 *
 * Discovers every mission's `providers.ts` at BUNDLE TIME (eager
 * `import.meta.glob`) and composes them into a `<MissionProviders>`
 * wrapper that `App.tsx` mounts inside `RxProvider`. Deliberately
 * separate from `plugins/registry.ts`, which handles lazy page and
 * builder discovery — page manifests and app-root lifecycle
 * infrastructure are different concerns.
 *
 * Eager discovery is required: providers must exist when
 * RxProvider's WebSocket starts delivering messages (including the
 * mission `EventOps.on_client_connect` replay). Lazy loading would miss it.
 * Eager resolution also sidesteps the async `/api/config` fetch that
 * determines the active mission — the provider tree renders every
 * discovered provider regardless of active-mission state. Mission-owned
 * providers should gate themselves on the active mission when multiple
 * missions are bundled into one frontend.
 */
import type { ComponentType, PropsWithChildren, ReactElement, ReactNode } from 'react'

type ProviderModule = { default: ComponentType<PropsWithChildren>[] }
const providerModules = import.meta.glob<ProviderModule>(
  './**/providers.ts',
  { eager: true },
)

const allProviders: ComponentType<PropsWithChildren>[] = []
for (const path of Object.keys(providerModules).sort()) {
  const mod = providerModules[path]
  if (Array.isArray(mod.default)) {
    allProviders.push(...mod.default)
  }
}

/** Composed mount slot for every mission-supplied provider.
 *  Wraps `children` outside-in so later providers can consume
 *  earlier providers' context if they need to. */
export function MissionProviders({ children }: PropsWithChildren): ReactElement {
  return allProviders.reduceRight<ReactNode>(
    (acc, P) => <P>{acc}</P>,
    children,
  ) as ReactElement
}
