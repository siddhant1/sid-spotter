import { useEffect, useRef, useState } from 'react'
import type { HeatMetric } from '../types'
import { METRIC_BANDS, METRIC_INFO, RISK_COLORS, RISK_LABELS } from '../risk'
import { clock } from '../format'

interface Props {
  hours: number // frames, e.g. 49 -> slider 0..48
  hour: number
  onHour: (h: number) => void
  metric: HeatMetric
  onMetric: (m: HeatMetric) => void
  start: number | null // epoch ms of hour 0
  arrivalHour: number | null
  loading: boolean
  error: string | null
  readout: string | null
}

const PLAY_HOURS_PER_SEC = 3

export default function TimeBar(p: Props) {
  const [playing, setPlaying] = useState(false)
  const max = Math.max(1, p.hours - 1)
  const hourRef = useRef(p.hour)
  hourRef.current = p.hour

  useEffect(() => {
    if (!playing) return
    let raf = 0
    let last = performance.now()
    const tick = (now: number) => {
      const next = hourRef.current + ((now - last) / 1000) * PLAY_HOURS_PER_SEC
      last = now
      if (next >= max) {
        p.onHour(max)
        setPlaying(false)
        return
      }
      p.onHour(next)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, max])

  const disabled = p.start == null
  const legend = p.metric === 'risk' ? RISK_LABELS.map((l) => l) : bandLabels(p.metric)

  return (
    <div className="timebar">
      <div className="tb-top">
        <div className="segmented small" role="tablist" aria-label="Heatmap layer">
          {(Object.keys(METRIC_INFO) as HeatMetric[]).map((m) => (
            <button key={m} type="button" role="tab" aria-selected={p.metric === m} className={p.metric === m ? 'is-on' : ''} onClick={() => p.onMetric(m)}>
              {METRIC_INFO[m].label}
            </button>
          ))}
        </div>
        <div className="tb-time">
          {p.loading ? (
            <span className="muted">Loading corridor forecast…</span>
          ) : p.error ? (
            <span className="bad">{p.error}</span>
          ) : disabled ? (
            <span className="muted">Plan a trip to see the forecast heatmap</span>
          ) : (
            <>
              <b>+{Math.floor(p.hour)}h</b> <span>{clock(p.start! + p.hour * 3_600_000)}</span>
              {p.readout && <span className="tb-readout">{p.readout}</span>}
            </>
          )}
        </div>
      </div>
      <div className="tb-row">
        <button
          type="button"
          className="play"
          disabled={disabled}
          aria-label={playing ? 'Pause' : 'Play forecast'}
          onClick={() => {
            if (!playing && p.hour >= max) p.onHour(0)
            setPlaying(!playing)
          }}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <div className="slider">
          <input
            type="range"
            min={0}
            max={max}
            step="any"
            value={p.hour}
            disabled={disabled}
            aria-label="Hours after departure"
            onChange={(e) => {
              setPlaying(false)
              p.onHour(Number(e.target.value))
            }}
          />
          <div className="ticks" aria-hidden>
            {Array.from({ length: max / 6 + 1 }, (_, i) => (
              <span key={i} style={{ left: `${((i * 6) / max) * 100}%` }}>
                {i * 6}h
              </span>
            ))}
            {p.arrivalHour != null && p.arrivalHour <= max && (
              <span className="arrival" style={{ left: `${(p.arrivalHour / max) * 100}%` }} title="Selected route arrives">
                ⚑
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="legend">
        {legend.map((l, i) => (
          <span key={l}>
            <i style={{ background: RISK_COLORS[i] }} />
            {l}
          </span>
        ))}
      </div>
    </div>
  )
}

function bandLabels(metric: Exclude<HeatMetric, 'risk'>): string[] {
  const b = METRIC_BANDS[metric]
  const u = METRIC_INFO[metric].unit
  return [`<${b[1]}`, `${b[1]}–${b[2]}`, `${b[2]}–${b[3]}`, `${b[3]}–${b[4]}`, `${metric === 'wind' ? '≥' : '>'}${b[4]} ${u}`]
}
