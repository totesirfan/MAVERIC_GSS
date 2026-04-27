import { lazy } from 'react'
import { Camera, Compass, BatteryCharging } from 'lucide-react'
import type { PluginPageDef } from '@/plugins/registry'

const plugins: PluginPageDef[] = [
  {
    id: 'imaging',
    name: 'Imaging',
    description: 'Image downlink viewer',
    icon: Camera,
    category: 'mission',
    order: 10,
    component: lazy(() => import('./ImagingPage')),
  },
  {
    id: 'gnc',
    name: 'GNC',
    description: 'MTQ register dashboard',
    icon: Compass,
    category: 'mission',
    order: 20,
    keepAlive: true,   // keep hook state across tab switches
    subroutes: ['registers'],
    component: lazy(() => import('./gnc/GNCPage')),
  },
  {
    id: 'eps',
    name: 'EPS',
    description: 'Power bus dashboard',
    icon: BatteryCharging,
    category: 'mission',
    order: 25,
    component: lazy(() => import('./eps/EpsPage')),
  },
]

export default plugins
