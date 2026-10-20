export type RiskLevel = 0 | 1 | 2 | 3 | 4

export interface Place {
  label: string
  lat: number
  lon: number
}

export interface Weather {
  wind_mph: number | null
  gust_mph: number | null
  rain_in_hr: number | null
  snow_in_hr: number | null
}

export interface Assessment {
  level: RiskLevel
  label: string
  wind: RiskLevel
  rain: RiskLevel
  snow: RiskLevel
  driver: 'wind' | 'rain' | 'snow' | 'none'
  load_rule: string | null
}

export interface Checkpoint {
  index: number
  mile: number
  lat: number
  lon: number
  drive_s: number
  eta: string
  weather: Weather | null
  risk: Assessment | null
  span_mi: [number, number]
}

export interface Segment {
  level: RiskLevel | null
  coords: [number, number][]
}

export interface Route {
  id: string
  name: string
  via: string
  source: 'alternative' | 'via'
  distance_mi: number
  drive_s: number
  elapsed_s: number
  arrival: string
  miles_by_level: number[]
  unknown_mi: number
  avg_risk: number
  max_level: RiskLevel | null
  checkpoints: Checkpoint[]
  segments: Segment[]
  bounds: [[number, number], [number, number]]
  rank: number
  recommended: boolean
}

export interface Recommendation {
  best: string
  order: string[]
  reasons: string[]
  safe: boolean
  advisory: string | null
}

export interface PlanRequest {
  origin: Place
  destination: Place
  departure: string
  load_lb: number
  interval_mi: 10 | 25 | 50
  hos: boolean
  simulate_storm: boolean
}

export interface PlanResponse {
  request: PlanRequest
  routes: Route[]
  recommendation: Recommendation
  warnings: string[]
  corridor: [number, number][]
  storm: Storm | null
  provider: { name: string; truck: Truck }
}

export interface Truck {
  gross_lb: number
  height_ft: number
  length_ft: number
  width_ft: number
  max_speed_mph: number
}

export interface Storm {
  lat: number
  lon: number
  peak_epoch: number
}

export interface HeatmapResponse {
  grid: { lat0: number; lon0: number; dlat: number; dlon: number; rows: number; cols: number }
  cells: [number, number][]
  start: string
  hours: number
  times: string[]
  wind: (number | null)[]
  gust: (number | null)[]
  rain: (number | null)[]
  snow: (number | null)[]
  risk: number[]
}

export type HeatMetric = 'risk' | 'wind' | 'rain' | 'snow'
