import type { LatLon, Mode } from './types'

/** Ссылки «Вести в навигаторе»: открываются в новой вкладке, на телефоне — в приложении навигатора. */
export type NavProvider = 'yandex' | 'dgis' | 'google'
export const NAV_PROVIDERS: { id: NavProvider; label: string }[] = [
  { id: 'yandex', label: 'Яндекс Карты' },
  { id: 'dgis', label: '2GIS' },
  { id: 'google', label: 'Google Maps' },
]

const f = (n: number) => n.toFixed(5).replace(/0+$/, '').replace(/\.$/, '')
const ll = (p: LatLon) => `${f(p.lat)},${f(p.lon)}`

const YANDEX_MODE: Record<Mode, string> = { walk: 'pd', car: 'auto', transit: 'mt' }
const GOOGLE_MODE: Record<Mode, string> = { walk: 'walking', car: 'driving', transit: 'transit' }
const DGIS_MODE: Record<Mode, string> = { walk: 'pedestrian', car: 'car', transit: 'bus' }

/** points[0] — старт (уже огрублённая локация запроса), дальше — остановки по порядку. */
export function navUrl(provider: NavProvider, points: LatLon[], mode: Mode): string {
  if (provider === 'yandex') {
    return `https://yandex.kz/maps/?rtext=${points.map(ll).join('~')}&rtt=${YANDEX_MODE[mode]}`
  }
  if (provider === 'google') {
    const origin = points[0]
    const dest = points[points.length - 1]
    const via = points.slice(1, -1)
    const q = new URLSearchParams({ api: '1', origin: ll(origin), destination: ll(dest), travelmode: GOOGLE_MODE[mode] })
    if (via.length) q.set('waypoints', via.map(ll).join('|'))
    return `https://www.google.com/maps/dir/?${q.toString()}`
  }
  // 2GIS: порядок lon,lat, точки через «|»
  const pts = points.map((p) => `${f(p.lon)},${f(p.lat)}`).join('|')
  return `https://2gis.kz/astana/directions/tab/${DGIS_MODE[mode]}/points/${encodeURIComponent(pts)}`
}
