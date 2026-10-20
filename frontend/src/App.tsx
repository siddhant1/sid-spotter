import { memo, useCallback, useEffect, useMemo, useState } from 'react'
import type L from 'leaflet'
import { fetchHeatmap, planTrip } from './api'
import { HeatmapCanvas } from './heatmap'
import { METRIC_INFO, RISK_LABELS } from './risk'
import type { HeatMetric, HeatmapResponse, PlanRequest, PlanResponse } from './types'
import MapView from './components/MapView'
import PlanForm from './components/PlanForm'
import ResultsPanel from './components/Results'
import TimeBar from './components/TimeBar'
import './App.css'

const Results = memo(ResultsPanel)
const MemoMap = memo(MapView)

export default function App() {
  const [plan, setPlan] = useState<PlanResponse | null>(null)
  const [planning, setPlanning] = useState(false)
  const [planError, setPlanError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [focus, setFocus] = useState<{ routeId: string; index: number; nonce: number } | null>(null)

  const [heatData, setHeatData] = useState<HeatmapResponse | null>(null)
  const [heatLoading, setHeatLoading] = useState(false)
  const [heatError, setHeatError] = useState<string | null>(null)
  const [metric, setMetric] = useState<HeatMetric>('risk')
  const [hour, setHour] = useState(0)
  const [hover, setHover] = useState<L.LatLng | null>(null)

  const submit = useCallback(async (req: PlanRequest) => {
    setPlanning(true)
    setPlanError(null)
    try {
      const result = await planTrip(req)
      setPlan(result)
      setSelectedId(result.recommendation.best)
      setFocus(null)
      setHour(0)
    } catch (e) {
      setPlanError((e as Error).message)
    } finally {
      setPlanning(false)
    }
  }, [])

  // The heatmap loads after the routes so the map is useful immediately.
  useEffect(() => {
    if (!plan) return
    let cancelled = false
    setHeatData(null)
    setHeatLoading(true)
    setHeatError(null)
    fetchHeatmap(plan.corridor, plan.request.departure, plan.request.load_lb, plan.storm)
      .then((d) => !cancelled && setHeatData(d))
      .catch((e) => !cancelled && setHeatError((e as Error).message))
      .finally(() => !cancelled && setHeatLoading(false))
    return () => {
      cancelled = true
    }
  }, [plan])

  const heat = useMemo(() => (heatData ? new HeatmapCanvas(heatData) : null), [heatData])
  const heatStart = heatData ? Date.parse(heatData.start) : null

  const selected = plan?.routes.find((r) => r.id === selectedId) ?? null
  const arrivalHour = selected && heatStart != null ? (Date.parse(selected.arrival) - heatStart) / 3_600_000 : null

  const readout = useMemo(() => {
    if (!heat || !hover) return null
    const cell = heat.cellAt(hover.lat, hover.lng)
    if (cell == null) return null
    const v = heat.valueAt(cell, metric, hour)
    if (v == null) return null
    if (metric === 'risk') return `Cursor: ${RISK_LABELS[Math.round(v)]}`
    return `Cursor: ${v.toFixed(metric === 'wind' ? 0 : 2)} ${METRIC_INFO[metric].unit}`
  }, [heat, hover, metric, hour])

  const onFocusCheckpoint = useCallback(
    (routeId: string, index: number) => setFocus({ routeId, index, nonce: Date.now() }),
    [],
  )

  return (
    <div className="app">
      <aside className="panel">
        <header className="brand">
          <div className="brand-mark" aria-hidden>
            ◆
          </div>
          <div>
            <h1>SafeRoute</h1>
            <p>Weather-aware route planning for trucks</p>
          </div>
        </header>
        <PlanForm loading={planning} onSubmit={submit} />
        {planError && <p className="form-error panel-error">{planError}</p>}
        {plan && selectedId ? (
          <Results plan={plan} selectedId={selectedId} onSelect={setSelectedId} onFocusCheckpoint={onFocusCheckpoint} />
        ) : (
          !planning && <Intro />
        )}
      </aside>
      <main className="map-area">
        <MemoMap
          plan={plan}
          selectedId={selectedId}
          onSelect={setSelectedId}
          focus={focus}
          heat={heat}
          metric={metric}
          hour={hour}
          heatStart={heatStart}
          onHover={setHover}
        />
        {planning && <div className="map-busy">Fetching routes and forecasts…</div>}
        <TimeBar
          hours={heatData?.hours ?? 49}
          hour={hour}
          onHour={setHour}
          metric={metric}
          onMetric={setMetric}
          start={heatStart}
          arrivalHour={arrivalHour}
          loading={heatLoading}
          error={heatError}
          readout={readout}
        />
      </main>
    </div>
  )
}

function Intro() {
  return (
    <section className="intro">
      <h3>How it works</h3>
      <ol>
        <li>Three truck routes come from TomTom. They avoid roads the truck's weight and size aren't allowed on, use truck speeds and expect traffic at your departure time.</li>
        <li>Each route is sampled every 10, 25 or 50 miles. The forecast at each checkpoint is read at the time the truck gets there.</li>
        <li>Wind, rain and snow are classified with the risk table. Load rules then raise wind risk for heavy trucks.</li>
        <li>
          The recommended route has the fewest Severe miles, then the fewest High miles, then the lowest average risk, then the
          shortest time.
        </li>
      </ol>
    </section>
  )
}
