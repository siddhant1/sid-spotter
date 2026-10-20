import type { PlanResponse, Route } from '../types'
import { RISK_COLORS, RISK_LABELS, UNKNOWN_COLOR, riskColor } from '../risk'
import { clock, duration, miles, num } from '../format'

interface Props {
  plan: PlanResponse
  selectedId: string
  onSelect: (id: string) => void
  onFocusCheckpoint: (routeId: string, index: number) => void
}

export default function Results({ plan, selectedId, onSelect, onFocusCheckpoint }: Props) {
  const rec = plan.recommendation
  const best = plan.routes.find((r) => r.id === rec.best)!
  const ranked = [...plan.routes].sort((a, b) => a.rank - b.rank)
  const selected = plan.routes.find((r) => r.id === selectedId)!

  return (
    <div className="results">
      <section className={`rec ${rec.safe ? '' : 'is-unsafe'}`} aria-live="polite">
        <div className="rec-eyebrow">{rec.safe ? 'Recommended' : 'No safe route at this time'}</div>
        <h2>
          {best.name} <span className="muted">via {best.via}</span>
        </h2>
        <p className="rec-stats">
          {miles(best.distance_mi)} · {duration(best.elapsed_s)} · arrives {clock(best.arrival)}
        </p>
        <p className="rec-truck">
          {plan.provider.name} routing · {Math.round(plan.provider.truck.gross_lb).toLocaleString()} lb gross ·{' '}
          {feetInches(plan.provider.truck.height_ft)} tall · {plan.provider.truck.length_ft} ft long
        </p>
        {rec.advisory && <p className="rec-advisory">{rec.advisory}</p>}
        {rec.reasons.length > 0 && (
          <ul className="rec-reasons">
            {rec.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        )}
      </section>

      {plan.storm && (
        <p className="warning is-demo">
          Simulated storm active: a synthetic winter storm is layered on the real forecast near Route{' '}
          {plan.routes[0].id}'s midpoint. Not real weather.
        </p>
      )}

      {plan.warnings.map((w) => (
        <p key={w} className="warning">
          {w}
        </p>
      ))}

      <div className="route-cards" role="radiogroup" aria-label="Route options">
        {ranked.map((r) => (
          <RouteCard key={r.id} route={r} selected={r.id === selectedId} onSelect={() => onSelect(r.id)} />
        ))}
      </div>

      <section className="checkpoints">
        <h3>
          {selected.name} checkpoints <span className="muted">every {plan.request.interval_mi} mi</span>
        </h3>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Mile</th>
                <th>ETA</th>
                <th title="Sustained wind (gust)">Wind</th>
                <th>Rain</th>
                <th>Snow</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {selected.checkpoints.map((cp) => (
                <tr key={cp.index} onClick={() => onFocusCheckpoint(selected.id, cp.index)} tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && onFocusCheckpoint(selected.id, cp.index)}>
                  <td className="num">{Math.round(cp.mile)}</td>
                  <td>{clock(cp.eta)}</td>
                  <td className="num">
                    {num(cp.weather?.wind_mph)}
                    <span className="muted"> ({num(cp.weather?.gust_mph)})</span>
                  </td>
                  <td className="num">{num(cp.weather?.rain_in_hr, 2)}</td>
                  <td className="num">{num(cp.weather?.snow_in_hr, 2)}</td>
                  <td>
                    <span className="risk-pill" style={{ background: riskColor(cp.risk?.level) }}
                      title={cp.risk?.load_rule ?? undefined}>
                      {cp.risk ? cp.risk.label : 'No data'}
                      {cp.risk?.load_rule ? ' ⚖' : ''}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="fineprint">Wind in mph (gust), rain and snow in in/hr. ⚖ = raised by a load rule. Times in your local zone.</p>
      </section>
    </div>
  )
}

function feetInches(ft: number): string {
  const inches = Math.round(ft * 12)
  return `${Math.floor(inches / 12)}′${inches % 12}″`
}

function RouteCard({ route, selected, onSelect }: { route: Route; selected: boolean; onSelect: () => void }) {
  const total = route.distance_mi || 1
  return (
    <button type="button" role="radio" aria-checked={selected} className={`route-card ${selected ? 'is-selected' : ''}`} onClick={onSelect}>
      <div className="rc-head">
        <span className="rc-id">{route.id}</span>
        <span className="rc-via">{route.via}</span>
        {route.recommended && <span className="rc-badge">Best</span>}
      </div>
      <div className="rc-stats">
        <span>
          <b>{duration(route.elapsed_s)}</b>
          {route.elapsed_s !== route.drive_s && <span className="muted"> ({duration(route.drive_s)} driving)</span>}
        </span>
        <span>{miles(route.distance_mi)}</span>
        <span>arr. {clock(route.arrival)}</span>
      </div>
      <div className="riskbar" aria-label="Miles by risk level">
        {route.miles_by_level.map((m, lvl) =>
          m > 0 ? <span key={lvl} style={{ width: `${(m / total) * 100}%`, background: RISK_COLORS[lvl] }} /> : null,
        )}
        {route.unknown_mi > 0 && <span style={{ width: `${(route.unknown_mi / total) * 100}%`, background: UNKNOWN_COLOR }} />}
      </div>
      <dl className="rc-metrics">
        <div>
          <dt>Severe+</dt>
          <dd className={route.miles_by_level[3] + route.miles_by_level[4] > 0 ? 'bad' : ''}>
            {Math.round(route.miles_by_level[3] + route.miles_by_level[4])} mi
          </dd>
        </div>
        <div>
          <dt>High</dt>
          <dd>{Math.round(route.miles_by_level[2])} mi</dd>
        </div>
        <div>
          <dt>Avg risk</dt>
          <dd>{route.avg_risk.toFixed(2)}</dd>
        </div>
        <div>
          <dt>Worst</dt>
          <dd>
            <span className="dot" style={{ background: riskColor(route.max_level) }} />
            {route.max_level == null ? '–' : RISK_LABELS[route.max_level]}
          </dd>
        </div>
      </dl>
    </button>
  )
}
