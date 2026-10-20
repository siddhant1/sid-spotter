import { memo, useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import { CircleMarker, MapContainer, Marker, Pane, Polyline, Popup, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import type { Checkpoint, HeatMetric, PlanResponse, Route } from '../types'
import { HeatmapCanvas } from '../heatmap'
import { RISK_LABELS, riskColor } from '../risk'
import { clock, duration, num } from '../format'

interface Props {
  plan: PlanResponse | null
  selectedId: string | null
  onSelect: (id: string) => void
  focus: { routeId: string; index: number; nonce: number } | null
  heat: HeatmapCanvas | null
  metric: HeatMetric
  hour: number
  heatStart: number | null // epoch ms of slider hour 0
  onHover: (latlng: L.LatLng | null) => void
}

const US_CENTER: L.LatLngExpression = [39.5, -98.35]

export default function MapView(props: Props) {
  const { plan, selectedId } = props
  const ordered = useMemo(() => {
    // Draw the selected route last so it sits on top.
    const routes = plan?.routes ?? []
    return [...routes.filter((r) => r.id !== selectedId), ...routes.filter((r) => r.id === selectedId)]
  }, [plan, selectedId])

  return (
    <MapContainer center={US_CENTER} zoom={4} maxZoom={16} preferCanvas zoomControl={false} className="map">
      <TileLayer
        url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
        attribution='Tiles &copy; Esri · Weather: <a href="https://open-meteo.com">Open-Meteo</a> · Routing: <a href="https://project-osrm.org">OSRM</a> · <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        maxZoom={16}
      />
      <Pane name="heat" style={{ zIndex: 320 }} />
      <Pane name="labels" style={{ zIndex: 340, pointerEvents: 'none' }}>
        <TileLayer url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}" maxZoom={16} />
      </Pane>
      <ZoomControlRight />
      <HeatLayer heat={props.heat} metric={props.metric} hour={props.hour} />
      <HoverTracker onHover={props.onHover} />
      <FitToPlan plan={plan} />
      {ordered.map((r) => (
        <RouteLayer
          key={`${r.id}-${plan?.request.departure}`}
          route={r}
          selected={r.id === selectedId}
          onSelect={props.onSelect}
          focus={props.focus?.routeId === r.id ? props.focus : null}
        />
      ))}
      {plan && <Endpoints plan={plan} />}
      {plan && selectedId && props.heatStart != null && (
        <Truck route={plan.routes.find((r) => r.id === selectedId)!} at={props.heatStart + props.hour * 3_600_000} />
      )}
    </MapContainer>
  )
}

function ZoomControlRight() {
  const map = useMap()
  useEffect(() => {
    const zc = L.control.zoom({ position: 'topright' }).addTo(map)
    return () => {
      zc.remove()
    }
  }, [map])
  return null
}

function FitToPlan({ plan }: { plan: PlanResponse | null }) {
  const map = useMap()
  useEffect(() => {
    if (!plan) return
    const b = L.latLngBounds([])
    plan.routes.forEach((r) => b.extend(r.bounds))
    if (b.isValid()) map.flyToBounds(b, { padding: [40, 40], duration: 0.8 })
  }, [plan, map])
  return null
}

function HoverTracker({ onHover }: { onHover: Props['onHover'] }) {
  useMapEvents({
    mousemove: (e) => onHover(e.latlng),
    mouseout: () => onHover(null),
  })
  return null
}

function HeatLayer({ heat, metric, hour }: { heat: HeatmapCanvas | null; metric: HeatMetric; hour: number }) {
  const map = useMap()
  useEffect(() => {
    if (!heat) return
    // SVGOverlay positions and zoom-animates any element it is given; we hand it a canvas.
    const layer = L.svgOverlay(heat.canvas as unknown as SVGElement, heat.bounds, { pane: 'heat', interactive: false })
    layer.addTo(map)
    return () => {
      layer.remove()
    }
  }, [heat, map])
  useEffect(() => {
    heat?.render(metric, hour)
  }, [heat, metric, hour])
  return null
}

const RouteLayer = memo(function RouteLayer({
  route,
  selected,
  onSelect,
  focus,
}: {
  route: Route
  selected: boolean
  onSelect: (id: string) => void
  focus: { index: number; nonce: number } | null
}) {
  const map = useMap()
  const markers = useRef(new Map<number, L.CircleMarker>())
  const fullLine = useMemo(() => route.segments.flatMap((s) => s.coords), [route])
  const handlers = useMemo(() => ({ click: () => onSelect(route.id) }), [onSelect, route.id])
  const labelAt = route.checkpoints[Math.floor(route.checkpoints.length / 2)]

  useEffect(() => {
    if (!focus) return
    const m = markers.current.get(focus.index)
    if (!m) return
    map.flyTo(m.getLatLng(), Math.max(map.getZoom(), 8), { duration: 0.6 })
    m.openPopup()
  }, [focus, map])

  return (
    <>
      {selected ? (
        <>
          <Polyline positions={fullLine} pathOptions={{ color: '#1b2430', weight: 9, opacity: 0.85 }} interactive={false} />
          {route.segments.map((s, i) => (
            <Polyline
              key={i}
              positions={s.coords}
              pathOptions={{ color: riskColor(s.level), weight: 5, opacity: 1, lineCap: 'round' }}
              interactive={false}
            />
          ))}
        </>
      ) : (
        <>
          {/* Wide transparent line makes unselected routes easy to click. */}
          <Polyline positions={fullLine} pathOptions={{ color: '#000', weight: 16, opacity: 0 }} eventHandlers={handlers} />
          <Polyline
            positions={fullLine}
            pathOptions={{ color: '#55606d', weight: 4, opacity: 0.75, dashArray: '6 7' }}
            eventHandlers={handlers}
          />
        </>
      )}
      {route.checkpoints.map((cp) => (
        <CircleMarker
          key={cp.index}
          ref={(m) => {
            if (m) markers.current.set(cp.index, m)
            else markers.current.delete(cp.index)
          }}
          center={[cp.lat, cp.lon]}
          radius={selected ? 5.5 : 3.5}
          pathOptions={{
            color: '#fff',
            weight: selected ? 1.5 : 1,
            fillColor: riskColor(cp.risk?.level),
            fillOpacity: selected ? 1 : 0.8,
            opacity: selected ? 1 : 0.7,
          }}
          eventHandlers={selected ? undefined : handlers}
        >
          <Popup>
            <CheckpointPopup route={route} cp={cp} />
          </Popup>
        </CircleMarker>
      ))}
      {labelAt && (
        <CircleMarker center={[labelAt.lat, labelAt.lon]} radius={0} pathOptions={{ opacity: 0, fillOpacity: 0 }}>
          <Tooltip permanent direction="right" offset={[10, 0]} className={`route-chip ${selected ? 'is-selected' : ''}`}>
            <b>{route.id}</b> {duration(route.elapsed_s)}
            {route.recommended && <span className="chip-star"> ★</span>}
          </Tooltip>
        </CircleMarker>
      )}
    </>
  )
})

function CheckpointPopup({ route, cp }: { route: Route; cp: Checkpoint }) {
  const w = cp.weather
  const r = cp.risk
  return (
    <div className="cp-popup">
      <div className="cp-popup-head">
        <span>
          {route.name} · mile {Math.round(cp.mile)}
        </span>
        <span className="risk-pill" style={{ background: riskColor(r?.level) }}>
          {r ? r.label : 'No data'}
        </span>
      </div>
      <div className="cp-popup-eta">ETA {clock(cp.eta)}</div>
      <table>
        <tbody>
          <tr>
            <th>Wind</th>
            <td>
              {num(w?.wind_mph)} mph <span className="muted">(gust {num(w?.gust_mph)})</span>
            </td>
            <td>{r && RISK_LABELS[r.wind]}</td>
          </tr>
          <tr>
            <th>Rain</th>
            <td>{num(w?.rain_in_hr, 2)} in/hr</td>
            <td>{r && RISK_LABELS[r.rain]}</td>
          </tr>
          <tr>
            <th>Snow</th>
            <td>{num(w?.snow_in_hr, 2)} in/hr</td>
            <td>{r && RISK_LABELS[r.snow]}</td>
          </tr>
        </tbody>
      </table>
      {r?.load_rule && <div className="cp-popup-rule">Load rule: {r.load_rule}</div>}
    </div>
  )
}

const pinIcon = (cls: string) =>
  L.divIcon({ className: `pin ${cls}`, html: '<span></span>', iconSize: [18, 18], iconAnchor: [9, 9] })

function Endpoints({ plan }: { plan: PlanResponse }) {
  const { origin, destination } = plan.request
  return (
    <>
      <Marker position={[origin.lat, origin.lon]} icon={pinIcon('pin-origin')} title={origin.label} />
      <Marker position={[destination.lat, destination.lon]} icon={pinIcon('pin-dest')} title={destination.label} />
    </>
  )
}

const truckIcon = L.divIcon({
  className: 'truck',
  html: '<svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M3 6h11v9H3zM14 9h4l3 3v3h-7zM6.5 18.5a1.75 1.75 0 1 0 0-3.5 1.75 1.75 0 0 0 0 3.5zm11 0a1.75 1.75 0 1 0 0-3.5 1.75 1.75 0 0 0 0 3.5z"/></svg>',
  iconSize: [30, 30],
  iconAnchor: [15, 15],
})

/** Truck position at a wall-clock time: ETA -> mile (from checkpoints) -> point on the road. */
function Truck({ route, at }: { route: Route; at: number }) {
  const line = useMemo(() => {
    const pts = route.segments.flatMap((s) => s.coords)
    const cum = [0]
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + L.latLng(pts[i - 1]).distanceTo(L.latLng(pts[i])))
    return { pts, cum, etas: route.checkpoints.map((c) => Date.parse(c.eta)) }
  }, [route])

  const pos = useMemo(() => {
    const { pts, cum, etas } = line
    const cps = route.checkpoints
    let mile = route.distance_mi
    if (at <= etas[0]) mile = 0
    else {
      const i = etas.findIndex((t) => t >= at)
      if (i > 0) mile = cps[i - 1].mile + ((cps[i].mile - cps[i - 1].mile) * (at - etas[i - 1])) / (etas[i] - etas[i - 1] || 1)
    }
    // Simplified geometry is slightly shorter than the true route; scale to match.
    const target = (mile / route.distance_mi) * cum[cum.length - 1]
    let j = cum.findIndex((d) => d >= target)
    if (j <= 0) return pts[Math.max(0, j)] ?? pts[pts.length - 1]
    const f = (target - cum[j - 1]) / (cum[j] - cum[j - 1] || 1)
    return [pts[j - 1][0] + (pts[j][0] - pts[j - 1][0]) * f, pts[j - 1][1] + (pts[j][1] - pts[j - 1][1]) * f] as [number, number]
  }, [line, route, at])

  return <Marker position={pos} icon={truckIcon} interactive={false} zIndexOffset={1000} />
}
