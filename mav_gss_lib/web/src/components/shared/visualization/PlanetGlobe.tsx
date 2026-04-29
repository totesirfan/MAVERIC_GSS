import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import {
  geoOrthographic,
  geoPath,
  geoGraticule10,
  geoDistance,
  geoCircle,
} from 'd3-geo'
import { feature } from 'topojson-client'
import * as satellite from 'satellite.js'
import type { GeoPermissibleObjects } from 'd3-geo'
import type { FeatureCollection, Geometry, GeoJsonProperties, LineString } from 'geojson'
import type { GeometryObject, Topology } from 'topojson-specification'

// =============================================================================
//  PlanetGlobe — d3 orthographic Earth, rendered to SVG.
//
//  • Continents fetched from /countries-110m.json at mount
//  • Graticule is the standard 10° lat/lon grid
//  • SERC pin shows/fades when LA is in/near the visible hemisphere
//  • Rotation is driven by mouse position + slow auto-drift, lerped smooth
//  • Imperative d3: React owns the <path>/<circle> elements, refs capture
//    them, the rAF tick loop mutates `d`/`cx`/`cy` attributes directly so
//    we never re-render React 60 times per second
//  • Falls back to <StaticOrb /> if the atlas can't be loaded
// =============================================================================

// Local palette (matches the PreflightScreen welcome slate accent).
const SLATE_DIM = 'rgba(195, 203, 215, 0.5)'
const USC_GOLD  = '#FFCC00'

// USC SERC ground station (Los Angeles).
const GS_LON = -118.29
const GS_LAT = 34.02

// SVG coordinate system.
const VIEWBOX = 800
const CENTER  = VIEWBOX / 2
const RADIUS  = 260

// Rotation config.
const DRIFT_DEG_PER_SEC = 2.8
const MOUSE_LAMBDA_RANGE = 75
const MOUSE_PHI_RANGE    = 22
const PHI_BASE           = -18
const MOUSE_LERP         = 0.055

// Representative mission orbit propagated via satellite.js. SSO at 97.82°
// inclination, ~96.5 min period.
const TLE_LINE1 = '1 99999U 26001A   26182.53800926  .00000000  00000-0  15000-3 0  9999'
const TLE_LINE2 = '2 99999  97.8250 154.7171 0058009 348.1000 351.9980 14.91466332000019'

const SAT_ALT_KM     = 550
const EARTH_R_KM     = 6371
const HORIZON_DEG    = Math.acos(EARTH_R_KM / (EARTH_R_KM + SAT_ALT_KM)) * 180 / Math.PI
const HORIZON_RAD    = HORIZON_DEG * Math.PI / 180
const SAT_TRAIL_MAX  = 42     // number of ground-track samples retained

// Replay time scale — 1 real second = TIME_SCALE sim seconds.
// One orbit (~96.5 min) now plays in ~36s real time.
const TIME_SCALE = 160

// First LOS pass is aligned to this real-time mark so the operator
// always sees a pass at a known point in the animation.
const PASS_AT_REAL_SEC = 20

// Nominal vs LOS-active colors for the satellite + trail + footprint.
// When the sub-point is inside the coverage cap centered on SERC,
// everything swaps to gold to signal that the ground station has the sat.
const NOMINAL_SAT_FILL   = '#EAEFF6'
const NOMINAL_SAT_RING   = 'rgba(225, 232, 242, 0.55)'
const NOMINAL_LABEL_FILL = 'rgba(234, 239, 246, 0.85)'
const NOMINAL_FP_FILL    = 'rgba(215, 222, 232, 0.06)'
const NOMINAL_FP_STROKE  = 'rgba(215, 222, 232, 0.45)'
const NOMINAL_GLOW_INNER = 'rgba(234, 239, 246, 1)'
const NOMINAL_GLOW_MID   = 'rgba(205, 215, 230, 0.75)'
const NOMINAL_GLOW_OUTER = 'rgba(185, 195, 210, 0.4)'

const LOS_SAT_FILL   = USC_GOLD
const LOS_SAT_RING   = 'rgba(255, 204, 0, 0.75)'
const LOS_LABEL_FILL = USC_GOLD
const LOS_FP_FILL    = 'rgba(255, 204, 0, 0.12)'
const LOS_FP_STROKE  = 'rgba(255, 204, 0, 0.7)'
const LOS_GLOW_INNER = 'rgba(255, 210, 40, 1)'
const LOS_GLOW_MID   = 'rgba(255, 204, 0, 0.75)'
const LOS_GLOW_OUTER = 'rgba(255, 180, 0, 0.45)'

// TLE epoch → JS milliseconds.
function tleEpochMs(satrec: satellite.SatRec): number {
  const year = 2000 + satrec.epochyr
  return Date.UTC(year, 0, 1) + (satrec.epochdays - 1) * 86400000
}

// Propagate a satrec to the given Date and return the geodetic sub-point
// (lat/lon in degrees), or null if propagation fails.
function satSubPoint(satrec: satellite.SatRec, date: Date): { lat: number; lon: number } | null {
  const pv = satellite.propagate(satrec, date)
  if (!pv || !pv.position || typeof pv.position === 'boolean') return null
  const gmst = satellite.gstime(date)
  const geo = satellite.eciToGeodetic(pv.position, gmst)
  return {
    lat: geo.latitude * 180 / Math.PI,
    lon: geo.longitude * 180 / Math.PI,
  }
}

// Scan forward from `fromMs` until the sub-point first enters the
// coverage cap around SERC, then fine-step back to find the exact entry.
// Returns the entry timestamp in ms, or null if no pass found within maxHours.
function findFirstPassEntry(
  satrec: satellite.SatRec,
  fromMs: number,
  maxHours: number,
): number | null {
  const maxMs = fromMs + maxHours * 3600 * 1000
  const coarseStepMs = 30 * 1000
  for (let ms = fromMs; ms < maxMs; ms += coarseStepMs) {
    const sub = satSubPoint(satrec, new Date(ms))
    if (!sub) continue
    const dist = geoDistance([sub.lon, sub.lat], [GS_LON, GS_LAT])
    if (dist < HORIZON_RAD) {
      // Fine-step back to locate the exact entry time.
      for (let fine = ms - coarseStepMs; fine < ms; fine += 1000) {
        const s = satSubPoint(satrec, new Date(fine))
        if (!s) continue
        const d = geoDistance([s.lon, s.lat], [GS_LON, GS_LAT])
        if (d < HORIZON_RAD) return fine
      }
      return ms
    }
  }
  return null
}

export function PlanetGlobe({ satelliteLabel = 'SAT' }: { satelliteLabel?: string }) {
  const continentPathsRef = useRef<(SVGPathElement | null)[]>([])
  const graticulePathRef  = useRef<SVGPathElement | null>(null)
  const sercRingRef       = useRef<SVGCircleElement | null>(null)
  const sercDotRef        = useRef<SVGCircleElement | null>(null)
  const sercLabelRef      = useRef<SVGTextElement | null>(null)

  // Satellite visualization refs
  const footprintFillRef   = useRef<SVGPathElement | null>(null)
  const footprintStrokeRef = useRef<SVGPathElement | null>(null)
  const trailGroupRef      = useRef<SVGGElement | null>(null)
  const trailSegsRef       = useRef<SVGPathElement[]>([])
  const satRingRef         = useRef<SVGCircleElement | null>(null)
  const satCoreRef         = useRef<SVGCircleElement | null>(null)
  const satLabelRef        = useRef<SVGTextElement | null>(null)

  const [landFeatures, setLandFeatures] = useState<GeoPermissibleObjects[]>([])
  const [atlasFailed, setAtlasFailed]   = useState(false)

  // ------------------------------------------------------------
  // Effect 1 — fetch and decode the world atlas
  // ------------------------------------------------------------
  useEffect(() => {
    let cancelled = false
    fetch('/countries-110m.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((world: Topology<{ countries: GeometryObject }>) => {
        if (cancelled) return
        try {
          const land = feature(world, world.objects.countries) as FeatureCollection<Geometry, GeoJsonProperties>
          setLandFeatures(land.features)
        } catch (err) {
          console.warn('[PlanetGlobe] topojson decode failed:', err)
          setAtlasFailed(true)
        }
      })
      .catch((err) => {
        console.warn('[PlanetGlobe] atlas fetch failed:', err)
        if (!cancelled) setAtlasFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  // ------------------------------------------------------------
  // Effect 2 — once land data is ready, run the d3 render loop
  // ------------------------------------------------------------
  useEffect(() => {
    if (landFeatures.length === 0) return

    const proj = geoOrthographic()
      .scale(RADIUS)
      .translate([CENTER, CENTER])
      .clipAngle(90)
      .rotate([-60, PHI_BASE, 0])
    const pathGen = geoPath(proj)
    const graticuleData = geoGraticule10()

    // Parse TLE and precompute the first pass so we can anchor the
    // animation to it. This runs once when landFeatures become available.
    const satrec = satellite.twoline2satrec(TLE_LINE1, TLE_LINE2)
    const epochMs = tleEpochMs(satrec)
    const firstPassMs = findFirstPassEntry(satrec, epochMs, 48) ?? epochMs
    const simStartMs = firstPassMs - PASS_AT_REAL_SEC * TIME_SCALE * 1000

    // Mouse state (captured in closure so no React re-renders per frame).
    let targetMx = 0
    let targetMy = 0
    let smoothMx = 0
    let smoothMy = 0

    const onMouseMove = (e: MouseEvent) => {
      targetMx = (e.clientX / window.innerWidth  - 0.5) * 2
      targetMy = (e.clientY / window.innerHeight - 0.5) * 2
    }
    window.addEventListener('mousemove', onMouseMove)

    // Build the ground-track segment pool once (reused every frame).
    const trailGroup = trailGroupRef.current
    if (trailGroup && trailSegsRef.current.length === 0) {
      for (let i = 0; i < SAT_TRAIL_MAX - 1; i++) {
        const p = document.createElementNS('http://www.w3.org/2000/svg', 'path')
        p.setAttribute('fill', 'none')
        p.setAttribute('stroke', '#EAEFF6')
        p.setAttribute('stroke-width', '1.4')
        p.setAttribute('stroke-linecap', 'round')
        p.setAttribute('stroke-opacity', '0')
        trailGroup.appendChild(p)
        trailSegsRef.current.push(p)
      }
    }

    // Trail buffer (closure-local so the rAF loop can mutate without state).
    const satTrail: Array<{ lat: number; lon: number }> = []

    let rafId = 0
    let t0: number | null = null

    const tick = (t: number) => {
      rafId = requestAnimationFrame(tick)
      if (t0 === null) t0 = t
      const elapsedRealMs = t - t0

      // Sim time = pass_anchor + (real elapsed × time scale)
      const simDate = new Date(simStartMs + elapsedRealMs * TIME_SCALE)

      // Lerp mouse toward target for inertial feel.
      smoothMx += (targetMx - smoothMx) * MOUSE_LERP
      smoothMy += (targetMy - smoothMy) * MOUSE_LERP

      const driftLambda = (t / 1000) * DRIFT_DEG_PER_SEC
      const lambda = driftLambda + smoothMx * MOUSE_LAMBDA_RANGE
      const phi    = PHI_BASE    + smoothMy * MOUSE_PHI_RANGE
      proj.rotate([lambda, phi, 0])

      // Continents
      const paths = continentPathsRef.current
      for (let i = 0; i < paths.length && i < landFeatures.length; i++) {
        const el = paths[i]
        if (!el) continue
        const d = pathGen(landFeatures[i])
        el.setAttribute('d', d || '')
      }

      // Graticule
      if (graticulePathRef.current) {
        const d = pathGen(graticuleData)
        graticulePathRef.current.setAttribute('d', d || '')
      }

      // ---- Satellite sub-point (real TLE via satellite.js), LOS, footprint, trail ----
      const sub = satSubPoint(satrec, simDate)
      if (!sub) return
      const { lat: satLat, lon: satLon } = sub

      // Line-of-sight test — is SERC inside the satellite's coverage cap?
      // (geoDistance returns great-circle distance in radians.)
      const satToSerc = geoDistance([satLon, satLat], [GS_LON, GS_LAT])
      const inLOS = satToSerc < HORIZON_RAD

      // Pick color palette for this frame based on LOS.
      const satFill    = inLOS ? LOS_SAT_FILL   : NOMINAL_SAT_FILL
      const satRingCol = inLOS ? LOS_SAT_RING   : NOMINAL_SAT_RING
      const labelCol   = inLOS ? LOS_LABEL_FILL : NOMINAL_LABEL_FILL
      const fpFill     = inLOS ? LOS_FP_FILL    : NOMINAL_FP_FILL
      const fpStroke   = inLOS ? LOS_FP_STROKE  : NOMINAL_FP_STROKE
      const glowFilter = inLOS
        ? `drop-shadow(0 0 4px ${LOS_GLOW_INNER}) drop-shadow(0 0 12px ${LOS_GLOW_MID}) drop-shadow(0 0 24px ${LOS_GLOW_OUTER})`
        : `drop-shadow(0 0 3px ${NOMINAL_GLOW_INNER}) drop-shadow(0 0 9px ${NOMINAL_GLOW_MID}) drop-shadow(0 0 20px ${NOMINAL_GLOW_OUTER})`

      // SERC pin — show when LA is on the visible hemisphere, fade near limb.
      // Brightens and grows slightly when the satellite has LOS.
      const rot = proj.rotate()
      const viewCenter: [number, number] = [-rot[0], -rot[1]]
      const sercDist = geoDistance([GS_LON, GS_LAT], viewCenter)
      const sercVisible = sercDist < Math.PI / 2

      const ring  = sercRingRef.current
      const dot   = sercDotRef.current
      const label = sercLabelRef.current
      if (ring && dot) {
        if (sercVisible) {
          const coords = proj([GS_LON, GS_LAT])
          if (coords) {
            const [cx, cy] = coords
            const fadeStart = 0.8
            const fadeRatio = (sercDist / (Math.PI / 2) - fadeStart) / (1 - fadeStart)
            const edgeFade  = Math.max(0, Math.min(1, 1 - fadeRatio))
            ring.setAttribute('cx', String(cx))
            ring.setAttribute('cy', String(cy))
            ring.setAttribute('r', inLOS ? '14' : '11')
            ring.setAttribute('stroke-width', inLOS ? '1.6' : '1.2')
            ring.setAttribute('stroke-opacity', String((inLOS ? 1.0 : 0.9) * edgeFade))
            dot.setAttribute('cx', String(cx))
            dot.setAttribute('cy', String(cy))
            dot.setAttribute('r', inLOS ? '5.5' : '4')
            dot.setAttribute('opacity', String(edgeFade))
            if (label) {
              label.setAttribute('x', String(cx + 12))
              label.setAttribute('y', String(cy + 3))
              label.setAttribute('opacity', String(0.95 * edgeFade))
            }
          }
        } else {
          ring.setAttribute('stroke-opacity', '0')
          dot.setAttribute('opacity', '0')
          if (label) label.setAttribute('opacity', '0')
        }
      }

      // Coverage footprint
      const cap = geoCircle().center([satLon, satLat]).radius(HORIZON_DEG)()
      const footprintD = pathGen(cap) || ''
      if (footprintFillRef.current) {
        footprintFillRef.current.setAttribute('d', footprintD)
        footprintFillRef.current.setAttribute('fill', fpFill)
      }
      if (footprintStrokeRef.current) {
        footprintStrokeRef.current.setAttribute('d', footprintD)
        footprintStrokeRef.current.setAttribute('stroke', fpStroke)
      }

      // Trail buffer push
      satTrail.push({ lat: satLat, lon: satLon })
      if (satTrail.length > SAT_TRAIL_MAX) satTrail.shift()

      // Build segments (skipping anti-meridian jumps)
      const segs: Array<{ d: string; age: number }> = []
      for (let i = 1; i < satTrail.length; i++) {
        const a = satTrail[i - 1]
        const b = satTrail[i]
        if (Math.abs(a.lon - b.lon) > 180) continue
        const lineGeom: LineString = {
          type: 'LineString',
          coordinates: [
            [a.lon, a.lat],
            [b.lon, b.lat],
          ],
        }
        segs.push({
          d: pathGen(lineGeom) || '',
          age: i / satTrail.length,
        })
      }

      // Update trail segment pool (with LOS color swap)
      const trailEls = trailSegsRef.current
      for (let i = 0; i < trailEls.length; i++) {
        const el = trailEls[i]
        if (!el) continue
        if (i < segs.length) {
          el.setAttribute('d', segs[i].d)
          el.setAttribute('stroke', satFill)
          el.setAttribute('stroke-opacity', String(segs[i].age * 0.85))
        } else {
          el.setAttribute('stroke-opacity', '0')
        }
      }

      // Satellite dot (LOS-colored)
      const satDist = geoDistance([satLon, satLat], viewCenter)
      const satVisible = satDist < Math.PI / 2

      const satRing  = satRingRef.current
      const satCore  = satCoreRef.current
      const satLabel = satLabelRef.current
      if (satRing && satCore) {
        if (satVisible) {
          const satCoords = proj([satLon, satLat])
          if (satCoords) {
            const [subX, subY] = satCoords
            const dx = subX - CENTER
            const dy = subY - CENTER
            const d = Math.hypot(dx, dy)
            const outward = 24
            const ux = d > 0.1 ? dx / d : 0
            const uy = d > 0.1 ? dy / d : 1
            const sx = subX + ux * outward
            const sy = subY + uy * outward

            satRing.setAttribute('cx', String(sx))
            satRing.setAttribute('cy', String(sy))
            satRing.setAttribute('stroke', satRingCol)
            satRing.setAttribute('stroke-opacity', inLOS ? '0.85' : '0.55')
            satCore.setAttribute('cx', String(sx))
            satCore.setAttribute('cy', String(sy))
            satCore.setAttribute('fill', satFill)
            satCore.setAttribute('opacity', '1')
            satCore.style.filter = glowFilter
            if (satLabel) {
              satLabel.setAttribute('x', String(sx + 14))
              satLabel.setAttribute('y', String(sy + 4))
              satLabel.setAttribute('fill', labelCol)
              satLabel.setAttribute('opacity', '0.9')
            }
          }
        } else {
          satRing.setAttribute('stroke-opacity', '0')
          satCore.setAttribute('opacity', '0')
          if (satLabel) satLabel.setAttribute('opacity', '0')
        }
      }
    }

    rafId = requestAnimationFrame(tick)

    return () => {
      cancelAnimationFrame(rafId)
      window.removeEventListener('mousemove', onMouseMove)
    }
  }, [landFeatures])

  // ------------------------------------------------------------
  // Fallback — pure CSS orb if atlas failed to load.
  // ------------------------------------------------------------
  if (atlasFailed) return <StaticOrb />

  // ------------------------------------------------------------
  // Render
  // ------------------------------------------------------------
  return (
    <div
      className="relative"
      style={{
        width:  'clamp(300px, 58vmin, 480px)',
        height: 'clamp(300px, 58vmin, 480px)',
      }}
    >
      {/* Outer halo */}
      <div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: '-18%',
          background:
            'radial-gradient(circle, rgba(180, 188, 200, 0.07) 0%, rgba(180, 188, 200, 0.02) 40%, transparent 70%)',
          filter: 'blur(24px)',
        }}
      />

      {/* Globe SVG */}
      <svg
        viewBox={`0 0 ${VIEWBOX} ${VIEWBOX}`}
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
          filter: 'drop-shadow(0 0 42px rgba(180, 188, 200, 0.16))',
          overflow: 'visible',
        }}
      >
        <defs>
          <clipPath id="pg-orbClip">
            <circle cx={CENTER} cy={CENTER} r={RADIUS} />
          </clipPath>
          <radialGradient id="pg-orbBase" cx="50%" cy="50%" r="50%">
            <stop offset="0%"  stopColor="#14161c" />
            <stop offset="85%" stopColor="#0a0b10" />
            <stop offset="100%" stopColor="#040508" />
          </radialGradient>
          <radialGradient id="pg-orbLight" cx="32%" cy="28%" r="75%">
            <stop offset="0%"   stopColor="#c0c8d4" stopOpacity="0.24" />
            <stop offset="45%"  stopColor="#14161c" stopOpacity="0" />
            <stop offset="100%" stopColor="#000000" stopOpacity="0.88" />
          </radialGradient>
        </defs>

        {/* Base dark sphere */}
        <circle cx={CENTER} cy={CENTER} r={RADIUS} fill="url(#pg-orbBase)" />

        {/* Graticule (10° lat/lon grid) */}
        <g clipPath="url(#pg-orbClip)">
          <path
            ref={graticulePathRef}
            fill="none"
            stroke="rgba(200, 210, 220, 0.07)"
            strokeWidth="0.5"
          />
        </g>

        {/* Continents — one path per country, mutated every frame */}
        <g clipPath="url(#pg-orbClip)">
          {landFeatures.map((_, i) => (
            <path
              key={i}
              ref={(el) => {
                continentPathsRef.current[i] = el
              }}
              fill="rgba(165, 175, 190, 0.58)"
              stroke="rgba(210, 218, 230, 0.3)"
              strokeWidth="0.4"
            />
          ))}
        </g>

        {/* Coverage footprint (geodesic cap at the sat sub-point) */}
        <g clipPath="url(#pg-orbClip)">
          <path
            ref={footprintFillRef}
            fill="rgba(215, 222, 232, 0.06)"
            stroke="none"
          />
          <path
            ref={footprintStrokeRef}
            fill="none"
            stroke="rgba(215, 222, 232, 0.45)"
            strokeWidth="0.9"
            strokeDasharray="2.2 2.5"
          />
        </g>

        {/* Ground-track trail — segment pool is created imperatively */}
        <g ref={trailGroupRef} clipPath="url(#pg-orbClip)" />

        {/* USC SERC ground station pin — tight glow so the dot reads as
            a crisp point instead of a fuzzy halo. */}
        <g clipPath="url(#pg-orbClip)">
          <circle
            ref={sercRingRef}
            r="11"
            fill="none"
            stroke={USC_GOLD}
            strokeWidth="1.2"
            strokeOpacity="0"
          />
          <circle
            ref={sercDotRef}
            r="4"
            fill={USC_GOLD}
            stroke="#FFE070"
            strokeWidth="0.7"
            opacity="0"
            style={{
              filter: 'drop-shadow(0 0 3px rgba(255,204,0,0.85))',
            }}
          />
          <text
            ref={sercLabelRef}
            fontFamily='"JetBrains Mono", monospace'
            fontSize="11"
            fontWeight="600"
            fill={USC_GOLD}
            letterSpacing="1.2"
            opacity="0"
          >
            USC-SERC
          </text>
        </g>

        {/* Day/night lighting overlay */}
        <circle
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="url(#pg-orbLight)"
          pointerEvents="none"
        />

        {/* Rim */}
        <circle
          cx={CENTER}
          cy={CENTER}
          r={RADIUS}
          fill="none"
          stroke="rgba(205, 213, 225, 0.55)"
          strokeWidth="1.3"
          style={{ filter: 'drop-shadow(0 0 8px rgba(200, 208, 220, 0.5))' }}
        />

        {/* Satellite dot — drawn above the lighting/rim so it glows through.
            Not clipped so it can sit slightly outside the planet disc. */}
        <g>
          <circle
            ref={satRingRef}
            r="11"
            fill="none"
            stroke="rgba(225, 232, 242, 0.55)"
            strokeWidth="0.7"
            strokeOpacity="0"
          />
          <circle
            ref={satCoreRef}
            r="4.5"
            fill="#EAEFF6"
            opacity="0"
            style={{
              filter:
                'drop-shadow(0 0 3px rgba(234, 239, 246, 1)) ' +
                'drop-shadow(0 0 9px rgba(205, 215, 230, 0.75)) ' +
                'drop-shadow(0 0 20px rgba(185, 195, 210, 0.4))',
            }}
          />
          <text
            ref={satLabelRef}
            fontFamily='"JetBrains Mono", monospace'
            fontSize="11"
            fill="rgba(234, 239, 246, 0.85)"
            letterSpacing="1.3"
            opacity="0"
          >
            {satelliteLabel}
          </text>
        </g>
      </svg>

      {/* Pulse rings — three staggered framer-motion div rings */}
      <PulseRing delay={0}   />
      <PulseRing delay={1.8} />
      <PulseRing delay={3.6} />
    </div>
  )
}

// =============================================================================
//  StaticOrb — pure CSS fallback when d3/atlas aren't available
// =============================================================================

function StaticOrb() {
  return (
    <div
      className="relative"
      style={{
        width:  'clamp(300px, 58vmin, 480px)',
        height: 'clamp(300px, 58vmin, 480px)',
      }}
    >
      <div
        className="absolute rounded-full pointer-events-none"
        style={{
          inset: '-18%',
          background:
            'radial-gradient(circle, rgba(180, 188, 200, 0.07) 0%, rgba(180, 188, 200, 0.02) 40%, transparent 70%)',
          filter: 'blur(24px)',
        }}
      />
      <div
        className="absolute rounded-full"
        style={{
          inset: 0,
          background:
            'radial-gradient(circle at 32% 28%, rgba(192, 200, 212, 0.22) 0%, transparent 45%), ' +
            'radial-gradient(circle at 50% 50%, #14161c 0%, #0a0b10 70%, #040508 100%)',
          boxShadow:
            'inset -30px -30px 80px rgba(0, 0, 0, 0.7), ' +
            'inset 20px 20px 60px rgba(200, 210, 225, 0.05), ' +
            '0 0 50px rgba(180, 188, 200, 0.14)',
          border: `1px solid ${SLATE_DIM}`,
        }}
      />
      <PulseRing delay={0}   />
      <PulseRing delay={1.8} />
      <PulseRing delay={3.6} />
    </div>
  )
}

function PulseRing({ delay }: { delay: number }) {
  return (
    <motion.div
      className="absolute rounded-full pointer-events-none"
      style={{ inset: 0, border: `1px solid ${SLATE_DIM}` }}
      initial={{ scale: 1, opacity: 0 }}
      animate={{
        scale:   [1, 1.08, 1.5],
        opacity: [0,  0.55, 0],
      }}
      transition={{
        duration: 5.4,
        delay,
        repeat: Infinity,
        ease: 'easeOut',
        times: [0, 0.15, 1],
      }}
    />
  )
}
