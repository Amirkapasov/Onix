import type { LatLon } from './types'

/** Огрубление до 3 знаков (~100 м) — делается ДО отправки на сервер. */
export function coarsen(p: LatLon): LatLon {
  return { lat: Math.round(p.lat * 1000) / 1000, lon: Math.round(p.lon * 1000) / 1000 }
}

export function haversineM(a: LatLon, b: LatLon): number {
  const R = 6371000
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLon = toRad(b.lon - a.lon)
  const h =
    Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

export const ASTANA_CENTER: LatLon = { lat: 51.128, lon: 71.43 }

// ---- Время: Астана UTC+5 ----
const OFFSET_MIN = 5 * 60

export type TimeSlot = 'now' | 'morning' | 'day' | 'evening' | 'night'
export const TIME_SLOTS: TimeSlot[] = ['now', 'morning', 'day', 'evening', 'night']
const SLOT_TIME: Record<Exclude<TimeSlot, 'now'>, [number, number]> = {
  morning: [9, 0],
  day: [13, 0],
  evening: [19, 0],
  night: [23, 30],
}

const pad = (n: number) => String(n).padStart(2, '0')

/** ISO-время в часовом поясе Астаны для выбранного слота (дата — сегодня по Астане). */
export function slotToIso(slot: TimeSlot): string {
  const astana = new Date(Date.now() + OFFSET_MIN * 60000)
  const y = astana.getUTCFullYear()
  const mo = pad(astana.getUTCMonth() + 1)
  const d = pad(astana.getUTCDate())
  const [h, m] = slot === 'now' ? [astana.getUTCHours(), astana.getUTCMinutes()] : SLOT_TIME[slot]
  return `${y}-${mo}-${d}T${pad(h)}:${pad(m)}:00+05:00`
}

/** "HH:MM" из ISO-строки, без перевода в локальный пояс браузера. */
export function isoClock(iso: string): string {
  const m = iso.match(/T(\d{2}):(\d{2})/)
  return m ? `${m[1]}:${m[2]}` : ''
}

export function formatDistance(m: number, lang: string): string {
  const km = lang === 'en' ? 'km' : 'км'
  const mm = lang === 'en' ? 'm' : 'м'
  if (m < 50) return `< 50 ${mm}`
  if (m < 1000) return `${Math.round(m / 10) * 10} ${mm}`
  const v = (m / 1000).toFixed(1)
  return `${lang === 'en' ? v : v.replace('.', ',')} ${km}`
}
