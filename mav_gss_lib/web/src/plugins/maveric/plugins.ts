import { lazy } from 'react'
import type { PluginPageDef } from '@/plugins/registry'

const plugins: PluginPageDef[] = [
  {
    id: 'imaging',
    name: 'Imaging',
    description: 'Image downlink viewer',
    icon: 'Camera',
    component: lazy(() => import('./ImagingPage')),
  },
]

export default plugins
