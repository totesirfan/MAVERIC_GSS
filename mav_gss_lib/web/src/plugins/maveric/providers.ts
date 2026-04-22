/**
 * MAVERIC provider manifest — discovered eagerly by the platform at
 * bundle time. Every provider listed here is composed into a wrapper
 * that mounts at the app root (inside RxProvider) so plugin state is
 * alive from app launch, independent of which page is visible.
 *
 * Copy to `mav_gss_lib/web/src/plugins/maveric/providers.ts`. Ensure
 * the import is synchronous (no `lazy()`) — providers must be ready
 * before RxProvider's WebSocket begins delivering messages.
 *
 * Platform/mission separation:
 *   • Platform defines the discovery mechanism (see plugins/missionRuntime.ts)
 *     and the mount slot (see App.tsx's <MissionProviders> wrapper).
 *   • Mission lists its providers here. Each is an ordinary React FC
 *     that accepts children and returns its context provider.
 *   • Do NOT import platform internals from provider files beyond the
 *     plugin-service API (usePluginServices) and the state-consumer
 *     hooks (useRxStatus, useSession). Any deeper coupling breaks the
 *     mission-replacement seam.
 */
import type { ComponentType, PropsWithChildren } from 'react'
import { EpsProvider } from './eps/EpsProvider'
import { GncProvider } from './gnc/GncProvider'

const providers: ComponentType<PropsWithChildren>[] = [
  EpsProvider,
  GncProvider,
]

export default providers
