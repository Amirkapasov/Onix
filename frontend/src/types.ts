// Типы строго по contracts/api.md

export type Lang = 'ru' | 'kk' | 'en'
export type Mode = 'walk' | 'car' | 'transit'

export interface LatLon {
  lat: number
  lon: number
}

export interface Filters {
  with_kids?: boolean
  accessibility?: boolean
  group_size?: number
  time_budget_min?: number | null
  indoor_only?: boolean | null
  categories?: string[]
}

export interface RecommendRequest {
  query: string
  location: LatLon
  location_label?: string
  client_time: string
  lang: Lang
  mode: Mode
  filters: Filters
  want_route: boolean
}

export interface ContextUsed {
  location?: string
  time?: string
  weather?: string | null
  mode?: string
  radius_m?: number
  filters?: string[]
  data_note?: string
}

export interface ParsedIntent {
  intent?: string
  time_budget_min?: number | null
  companions?: string
  constraints?: string[]
  keywords?: string[]
}

export type OpenState = 'open' | 'closed' | 'unknown'
export type Confidence = 'high' | 'medium' | 'low'

export interface OpenStatus {
  state: OpenState
  confidence: Confidence
  label?: string
  source?: string | null
}

export interface SourceRef {
  name: string
  url?: string | null
}

export interface Recommendation {
  poi_id: string
  name: string
  category: string
  lat: number
  lon: number
  distance_m: number
  travel_min: number
  visit_min?: [number, number] | number[] | null
  why: string
  what_to_do: string
  open_status: OpenStatus
  source_type: 'poi_data'
  sources?: SourceRef[]
  rating?: number | null
  badges?: string[]
}

export interface Idea {
  text: string
  source_type: 'generated_idea'
}

export interface RouteLeg {
  from: string
  to: string
  distance_m: number
  minutes: number
}

export interface Route {
  stops: string[]
  legs: RouteLeg[]
  total_min: number
  geometry?: [number, number][] | null
  geometry_source?: string
}

export interface RecommendResponse {
  request_id?: string
  context_used?: ContextUsed
  parsed_intent?: ParsedIntent
  recommendations: Recommendation[]
  ideas?: Idea[]
  route?: Route | null
  warnings?: string[]
  llm?: { provider?: string; model?: string; latency_ms?: number } | null
}

export interface Preset {
  id: string
  label: string
  location: LatLon
  location_label?: string
  query: string
  client_time?: string
  filters?: Filters
  icon?: string
  mode?: Mode
}

export interface ApiErrorBody {
  error: { code: string; message: string }
}

export interface Poi {
  id: string
  name: string
  lat: number
  lon: number
  category: string
}
