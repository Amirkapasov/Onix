import type { Poi, Preset, RecommendRequest, RecommendResponse } from './types'
import { coarsen, haversineM, isoClock } from './geo'
import { weekdayOf } from './i18n'
import presetsMock from './mocks/presets.json'
import recommendMock from './mocks/recommend.json'

export const USE_MOCK = import.meta.env.VITE_USE_MOCK === '1'

export class ApiError extends Error {
  code: string
  constructor(code: string, message: string) {
    super(message)
    this.code = code
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError('network', 'Сервер недоступен')
  }
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const err = body?.error
    throw new ApiError(err?.code ?? `http_${res.status}`, err?.message ?? `HTTP ${res.status}`)
  }
  return body as T
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

export async function fetchPresets(): Promise<Preset[]> {
  if (USE_MOCK) return (presetsMock as { items: Preset[] }).items
  const data = await request<{ items: Preset[] }>('/api/presets')
  return data.items ?? []
}

export async function fetchPois(bbox: [number, number, number, number]): Promise<Poi[]> {
  if (USE_MOCK) return []
  const data = await request<{ items: Poi[] }>(`/api/pois?bbox=${bbox.map((v) => v.toFixed(3)).join(',')}`)
  return data.items ?? []
}

export async function fetchHealth(): Promise<boolean> {
  try {
    const res = await fetch('/api/health')
    return res.ok
  } catch {
    return false
  }
}

export async function recommend(req: RecommendRequest, presetId?: string): Promise<RecommendResponse> {
  // Приватность: огрубляем всегда, даже если вызывающий код забыл.
  const payload: RecommendRequest = { ...req, location: coarsen(req.location) }
  if (USE_MOCK) return mockRecommend(payload, presetId)
  return request<RecommendResponse>('/api/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

// ---------- Моки ----------
const DAYS_RU = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']

function pickMockKey(req: RecommendRequest, presetId?: string): string {
  const all = recommendMock as Record<string, unknown>
  if (presetId && presetId in all) return presetId
  const q = req.query.toLowerCase()
  const hour = Number(isoClock(req.client_time).slice(0, 2))
  if (/реб[её]н|дет|kid|child|бала/.test(q) || req.filters.with_kids) return 'kids_khan_shatyr'
  if (/ноч|night|түн/.test(q) || hour >= 23 || hour < 5) return 'night_nurzhol'
  if (/аэропорт|вылет|airport|flight|әуежай/.test(q)) return 'airport_2h'
  return 'megasilkway_walk'
}

async function mockRecommend(req: RecommendRequest, presetId?: string): Promise<RecommendResponse> {
  await sleep(900)
  const key = pickMockKey(req, presetId)
  const base = structuredClone((recommendMock as unknown as Record<string, RecommendResponse>)[key])
  // Подстраиваем мок под фактический запрос, чтобы «Что учтено» и расстояния были честными.
  const day = DAYS_RU[weekdayOf(req.client_time)]
  base.context_used = {
    ...base.context_used,
    location: `≈ ${req.location_label ?? 'выбранная точка'} (точность ~100 м)`,
    time: `${day}, ${isoClock(req.client_time)}`,
    mode: req.mode === 'car' ? 'на машине' : 'пешком',
  }
  if (req.weather_override) {
    const { temp_c, wind_ms } = req.weather_override
    const temp = `${temp_c > 0 ? '+' : temp_c < 0 ? '−' : ''}${Math.abs(temp_c)}°C`
    base.context_used.weather = `${temp}${wind_ms != null ? `, ветер ${wind_ms} м/с` : ''} (симуляция)`
  }
  const speed = req.mode === 'car' ? 500 : 80 // м/мин
  for (const r of base.recommendations) {
    const d = Math.round(haversineM(req.location, r) * 1.3)
    r.distance_m = d
    r.travel_min = Math.max(1, Math.round(d / speed))
  }
  if (base.route?.geometry?.length) base.route.geometry[0] = [req.location.lat, req.location.lon]
  if (base.route?.legs?.[0]) {
    const first = base.recommendations.find((r) => r.poi_id === base.route!.legs[0].to)
    if (first) {
      base.route.legs[0].distance_m = first.distance_m
      base.route.legs[0].minutes = first.travel_min
    }
  }
  return base
}
