import type { HeatMetric } from './types'

export const RISK_LABELS = ['Low', 'Moderate', 'High', 'Severe', 'No Travel'] as const
export const RISK_COLORS = ['#2f9e5b', '#e2b007', '#ef7d1a', '#d62839', '#6b1f8f'] as const
const RISK_RGB = RISK_COLORS.map((hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)))
export const UNKNOWN_COLOR = '#9aa3ad'

export const riskColor = (level: number | null | undefined) =>
  level == null || level < 0 ? UNKNOWN_COLOR : RISK_COLORS[level]

/** Band edges per metric, matching the risk table (value at which each level starts). */
export const METRIC_BANDS: Record<Exclude<HeatMetric, 'risk'>, number[]> = {
  wind: [0, 25, 35, 45, 55],
  rain: [0, 0.1, 0.25, 0.5, 1.0],
  snow: [0, 0.5, 1.0, 2.0, 3.0],
}

export const METRIC_INFO: Record<HeatMetric, { label: string; unit: string }> = {
  risk: { label: 'Risk', unit: '' },
  wind: { label: 'Wind', unit: 'mph' },
  rain: { label: 'Rain', unit: 'in/hr' },
  snow: { label: 'Snow', unit: 'in/hr' },
}

/** Map a raw value to a continuous 0–4 score aligned with the risk bands. */
export function bandScore(value: number, bands: number[]): number {
  if (value <= bands[0]) return 0
  for (let i = 1; i < bands.length; i++) {
    if (value < bands[i]) return i - 1 + (value - bands[i - 1]) / (bands[i] - bands[i - 1])
  }
  return 4
}

/** RGBA for a continuous 0–4 score: palette interpolation, calm areas faint. */
export function scoreRgba(score: number): [number, number, number, number] {
  const s = Math.max(0, Math.min(4, score))
  const i = Math.min(3, Math.floor(s))
  const f = s - i
  const a = RISK_RGB[i]
  const b = RISK_RGB[i + 1]
  const alpha = s < 1 ? 0.12 + 0.28 * s : 0.4 + 0.1 * (s - 1)
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f, alpha * 255]
}
