import type { HeatMetric, HeatmapResponse } from './types'
import { METRIC_BANDS, bandScore, scoreRgba } from './risk'

/**
 * Paints the forecast grid into a tiny canvas (one pixel per grid cell).
 * Leaflet stretches it over the corridor and the browser's bilinear scaling
 * smooths it. Re-rendering a frame is a single pass over a few hundred
 * cells, so dragging the time slider stays at 60 fps. Fractional hours blend
 * the two neighbouring forecast hours.
 */
export class HeatmapCanvas {
  readonly canvas: HTMLCanvasElement
  private ctx: CanvasRenderingContext2D
  private image: ImageData
  private index = new Map<number, number>() // r * cols + c -> cell index
  private data: HeatmapResponse

  constructor(data: HeatmapResponse) {
    this.data = data
    const { rows, cols } = data.grid
    this.canvas = document.createElement('canvas')
    this.canvas.width = cols
    this.canvas.height = rows
    this.canvas.className = 'heat-canvas'
    this.ctx = this.canvas.getContext('2d')!
    this.image = this.ctx.createImageData(cols, rows)
    data.cells.forEach(([r, c], i) => this.index.set(r * cols + c, i))
  }

  /** Geographic bounds of the canvas edges (cell centres are half a cell in). */
  get bounds(): [[number, number], [number, number]] {
    const { lat0, lon0, dlat, dlon, rows, cols } = this.data.grid
    return [
      [lat0 - dlat / 2, lon0 - dlon / 2],
      [lat0 + (rows - 0.5) * dlat, lon0 + (cols - 0.5) * dlon],
    ]
  }

  /** Raw value of a metric for one cell at a fractional hour, or null. */
  valueAt(cell: number, metric: HeatMetric, hour: number): number | null {
    const n = this.data.cells.length
    const h0 = Math.max(0, Math.min(this.data.hours - 1, Math.floor(hour)))
    const h1 = Math.min(this.data.hours - 1, h0 + 1)
    const f = hour - h0
    const arr = this.data[metric]
    let a: number | null = arr[h0 * n + cell]
    let b: number | null = arr[h1 * n + cell]
    if (metric === 'risk') {
      if (a === -1) a = null
      if (b === -1) b = null
    }
    if (a == null) return b
    if (b == null) return a
    return a + (b - a) * f
  }

  cellAt(lat: number, lon: number): number | null {
    const { lat0, lon0, dlat, dlon, rows, cols } = this.data.grid
    const r = Math.round((lat - lat0) / dlat)
    const c = Math.round((lon - lon0) / dlon)
    if (r < 0 || c < 0 || r >= rows || c >= cols) return null
    return this.index.get(r * cols + c) ?? null
  }

  render(metric: HeatMetric, hour: number) {
    const { rows, cols } = this.data.grid
    const px = this.image.data
    px.fill(0)
    const bands = metric === 'risk' ? null : METRIC_BANDS[metric]
    this.data.cells.forEach(([r, c], i) => {
      const v = this.valueAt(i, metric, hour)
      if (v == null) return
      const [R, G, B, A] = scoreRgba(bands ? bandScore(v, bands) : v)
      const o = ((rows - 1 - r) * cols + c) * 4
      px[o] = R
      px[o + 1] = G
      px[o + 2] = B
      px[o + 3] = A
    })
    this.ctx.putImageData(this.image, 0, 0)
  }
}
