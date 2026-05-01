/**
 * MAVERIC provider manifest — discovered eagerly by the platform at
 * bundle time. Every provider listed here is composed into a wrapper
 * that mounts at the app root (inside RxProvider) so plugin state is
 * alive from app launch, independent of which page is visible.
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
 *
 * GNC and EPS state is now served by the platform-level
 * `ParametersProvider` (mounted in App.tsx); their pages bind directly
 * to `useParameter` / `useParameterGroup`, so no per-domain provider
 * is needed here.
 */
import type { ComponentType, PropsWithChildren } from 'react'
import { FileChunkProvider } from './files/FileChunkProvider'

const providers: ComponentType<PropsWithChildren>[] = [
  FileChunkProvider,
]

export default providers
