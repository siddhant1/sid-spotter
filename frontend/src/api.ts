import type { HeatmapResponse, Place, PlanRequest, PlanResponse, Storm } from './types'

export class ApiError extends Error {}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(url, init)
  } catch {
    throw new ApiError('Could not reach the server. Check your connection and try again.')
  }
  const body = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    const fields = body.fields
      ? Object.entries(body.fields)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : JSON.stringify(v)}`)
          .join('; ')
      : ''
    throw new ApiError(fields || body.error || `Request failed (${resp.status})`)
  }
  return body as T
}

const post = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const geocode = (q: string, signal?: AbortSignal) =>
  request<{ results: Place[] }>(`/api/geocode?q=${encodeURIComponent(q)}`, { signal }).then((r) => r.results)

export const planTrip = (req: PlanRequest) => request<PlanResponse>('/api/plan', post(req))

export const fetchHeatmap = (corridor: [number, number][], departure: string, load_lb: number, storm: Storm | null) =>
  request<HeatmapResponse>('/api/heatmap', post({ corridor, departure, load_lb, storm }))
