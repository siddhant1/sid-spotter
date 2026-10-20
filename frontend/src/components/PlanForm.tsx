import { useState } from 'react'
import type { Place, PlanRequest } from '../types'
import { toLocalInput, tzName } from '../format'
import PlaceInput from './PlaceInput'

const EXAMPLES: { name: string; origin: Place; destination: Place }[] = [
  {
    name: 'Chicago → Denver',
    origin: { label: 'Chicago, Illinois, United States', lat: 41.8781, lon: -87.6298 },
    destination: { label: 'Denver, Colorado, United States', lat: 39.7392, lon: -104.9903 },
  },
  {
    name: 'Dallas → Atlanta',
    origin: { label: 'Dallas, Texas, United States', lat: 32.7763, lon: -96.7969 },
    destination: { label: 'Atlanta, Georgia, United States', lat: 33.749, lon: -84.388 },
  },
  {
    name: 'Seattle → Salt Lake City',
    origin: { label: 'Seattle, Washington, United States', lat: 47.6062, lon: -122.3321 },
    destination: { label: 'Salt Lake City, Utah, United States', lat: 40.7608, lon: -111.891 },
  },
]

function nextHour(): Date {
  const d = new Date()
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() + 1)
  return d
}

interface Props {
  loading: boolean
  onSubmit: (req: PlanRequest) => void
}

export default function PlanForm({ loading, onSubmit }: Props) {
  const [origin, setOrigin] = useState<Place | null>(null)
  const [destination, setDestination] = useState<Place | null>(null)
  const [departure, setDeparture] = useState(() => toLocalInput(nextHour()))
  const [load, setLoad] = useState('42000')
  const [interval, setIntervalMi] = useState<10 | 25 | 50>(25)
  const [hos, setHos] = useState(true)
  const [storm, setStorm] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const now = new Date()
  const max = new Date(now.getTime() + 7 * 86_400_000)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const loadLb = Number(load.replace(/,/g, ''))
    const dep = new Date(departure)
    if (!origin || !destination) return setError('Pick an origin and a destination from the suggestions.')
    if (!Number.isFinite(loadLb) || loadLb < 0 || loadLb > 200_000) return setError('Enter a load between 0 and 200,000 lb.')
    if (Number.isNaN(dep.getTime())) return setError('Enter a departure date and time.')
    setError(null)
    onSubmit({ origin, destination, departure: dep.toISOString(), load_lb: loadLb, interval_mi: interval, hos, simulate_storm: storm })
  }

  return (
    <form className="plan-form" onSubmit={submit} noValidate>
      <div className="od">
        <PlaceInput label="Origin" value={origin} onChange={setOrigin} placeholder="City or address" />
        <button
          type="button"
          className="swap"
          title="Swap origin and destination"
          aria-label="Swap origin and destination"
          onClick={() => {
            setOrigin(destination)
            setDestination(origin)
          }}
        >
          ⇅
        </button>
        <PlaceInput label="Destination" value={destination} onChange={setDestination} placeholder="City or address" />
      </div>
      <div className="examples">
        <span>Try:</span>
        {EXAMPLES.map((ex) => (
          <button
            key={ex.name}
            type="button"
            className="link"
            onClick={() => {
              setOrigin(ex.origin)
              setDestination(ex.destination)
            }}
          >
            {ex.name}
          </button>
        ))}
      </div>

      <div className="row">
        <label className="field">
          <span className="field-label">Departure ({tzName()})</span>
          <input
            type="datetime-local"
            value={departure}
            min={toLocalInput(now)}
            max={toLocalInput(max)}
            onChange={(e) => setDeparture(e.target.value)}
          />
        </label>
        <label className="field">
          <span className="field-label">Load weight (lb)</span>
          <input type="text" inputMode="numeric" value={load} onChange={(e) => setLoad(e.target.value)} />
        </label>
      </div>

      <div className="row row-end">
        <fieldset className="field">
          <legend className="field-label">Weather checkpoint every</legend>
          <div className="segmented">
            {([10, 25, 50] as const).map((n) => (
              <button key={n} type="button" className={interval === n ? 'is-on' : ''} onClick={() => setIntervalMi(n)}>
                {n} mi
              </button>
            ))}
          </div>
        </fieldset>
        <label className="check" title="Add a 30-min break after 8 h of driving and a 10-h rest after 11 h (FMCSA rules, simplified)">
          <input type="checkbox" checked={hos} onChange={(e) => setHos(e.target.checked)} />
          <span>Hours-of-service breaks</span>
        </label>
      </div>

      <label className="check check-demo" title="Overlay a synthetic winter storm (~45–54 mph wind, 1.5 in/hr snow) on the fastest route, timed to the truck's arrival. Use it to see the risk rules at work when real weather is calm.">
        <input type="checkbox" checked={storm} onChange={(e) => setStorm(e.target.checked)} />
        <span>Simulate a storm on the fastest route (demo)</span>
      </label>

      {error && <p className="form-error">{error}</p>}
      <button type="submit" className="primary" disabled={loading}>
        {loading ? 'Planning routes…' : 'Plan routes'}
      </button>
    </form>
  )
}
