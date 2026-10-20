import { memo, useEffect, useMemo, useState } from 'react'
import { Circle, CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, ZoomControl, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import { Moon, MousePointerClick } from 'lucide-react'
import type { Lang, LatLon, Poi, RecommendResponse } from '../types'
import { CATEGORY_LABELS } from '../i18n'
import { categoryIcon } from './Icons'
import { isOpenAt } from '../hours'

interface Props {
  location: LatLon
  result: RecommendResponse | null
  hovered: number | null
  onHover: (i: number | null) => void
  onPick: (p: LatLon) => void
  onMarkerClick: (i: number) => void
  pois: Poi[]
  hint: string
  coarseLabel: string
  lang: Lang
  night: boolean // вечер/ночь по времени запроса — «ночной город»
  clientTime: string // время запроса: какие точки POI сейчас открыты
  nightLabel: string
  hereLabel: string // «Вы здесь · у «Байтерек», бульвар Нуржол, 14» — постоянная подпись у точки старта
}

// Подложка: по умолчанию OSM (без ключа) с приглушающим фильтром — светлая и спокойная.
// CARTO/Stadia требуют ключ: VITE_TILE_URL=… и VITE_TILE_ATTR=… в .env.local.
const TILE_URL = import.meta.env.VITE_TILE_URL || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const TILE_ATTR =
  import.meta.env.VITE_TILE_ATTR || '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
const MUTED = !import.meta.env.VITE_TILE_URL

const NAVY = '#0b2545'
const GOLD = '#fec50c'
const AMBER = '#ff9f1c'
const TEAL = '#00afca'

type IconNode = [string, Record<string, string>][]
/** SVG-строка из данных иконки lucide (для divIcon Leaflet) — без рендера React и его хуков. */
function lucideSvg(Icon: unknown, size: number, stroke: number): string {
  const el = (Icon as { render: (p: object, r: null) => { props: { icon?: { node?: IconNode } } } }).render({}, null)
  const node = el.props.icon?.node ?? []
  const esc = (v: string) => v.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
  const inner = node
    .map(([tag, attrs]) => `<${tag} ${Object.entries(attrs).filter(([k]) => k !== 'key').map(([k, v]) => `${k}="${esc(String(v))}"`).join(' ')}/>`)
    .join('')
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`
}

// «Вы здесь» ночью — пульсирующее кольцо
const meIcon = L.divIcon({ className: '', html: '<div class="me-pulse"></div>', iconSize: [16, 16], iconAnchor: [8, 8] })

const iconCache = new Map<string, L.DivIcon>()
function pinIcon(n: number, active: boolean, category: string, lit: boolean) {
  const key = `${n}|${active}|${category}|${lit}`
  let icon = iconCache.get(key)
  if (!icon) {
    const cat = lucideSvg(categoryIcon(category), 13, 2.2)
    icon = L.divIcon({
      className: '',
      html: `<div class="rec-pin${active ? ' rec-pin--active' : ''}${lit ? ' rec-pin--lit' : ''}"><div class="rec-pin__dot">${n}</div><div class="rec-pin__cat">${cat}</div></div>`,
      iconSize: [36, 36],
      iconAnchor: [18, 18],
    })
    iconCache.set(key, icon)
  }
  return icon
}

function ClickToPick({ onPick }: { onPick: (p: LatLon) => void }) {
  useMapEvents({
    click(e) {
      onPick({ lat: e.latlng.lat, lon: e.latlng.lng })
    },
  })
  return null
}

// ?static=1 — без анимаций карты (для скриншотов headless-браузером)
const STATIC = new URLSearchParams(window.location.search).get('static') === '1'

function FitTo({ points, location }: { points: [number, number][]; location: LatLon }) {
  const map = useMap()
  useEffect(() => {
    // Прерванный перелёт (новая точка во время анимации, мобильный) оставляет маркеры и подписи в старых позициях —
    // по окончании движения принудительно пересчитываем слои.
    const resync = () => {
      map.invalidateSize({ animate: false })
      map.fire('viewreset')
    }
    map.once('moveend', resync)
    const cleanup = () => {
      map.off('moveend', resync)
    }
    if (points.length === 0) {
      if (STATIC) map.setView([location.lat, location.lon], Math.max(map.getZoom(), 14), { animate: false })
      else map.flyTo([location.lat, location.lon], Math.max(map.getZoom(), 14), { duration: 0.6 })
      return cleanup
    }
    const b = L.latLngBounds([[location.lat, location.lon], ...points])
    if (STATIC) map.fitBounds(b, { padding: [70, 70], maxZoom: 16, animate: false })
    else map.flyToBounds(b, { padding: [70, 70], maxZoom: 16, duration: 0.8 })
    return cleanup
  }, [JSON.stringify(points), location.lat, location.lon])
  return null
}

/** Leaflet не знает о смене размера контейнера (адаптив) — подсказываем. */
function ResizeWatcher() {
  const map = useMap()
  useEffect(() => {
    const ro = new ResizeObserver(() => map.invalidateSize())
    ro.observe(map.getContainer())
    return () => ro.disconnect()
  }, [map])
  return null
}

/**
 * Фоновые точки POI: один canvas вместо тысяч SVG-элементов, без подсказок и без анимаций (не грузит CPU).
 * Ночью открытые по часам места — статичное тёплое свечение: широкий полупрозрачный круг + яркий центр.
 */
const PoiLayer = memo(function PoiLayer({ pois, night, openIds }: { pois: Poi[]; night: boolean; openIds: Set<string> | null }) {
  const map = useMap()
  const renderer = useMemo(() => L.canvas({ padding: 0.2 }), [])
  useEffect(() => {
    const group = L.layerGroup()
    const base = { renderer, interactive: false, stroke: false } as const
    for (const p of pois) {
      const ll: [number, number] = [p.lat, p.lon]
      if (!night) {
        L.circleMarker(ll, { ...base, radius: 2.5, fillColor: NAVY, fillOpacity: 0.28 }).addTo(group)
      } else if (openIds?.has(p.id)) {
        L.circleMarker(ll, { ...base, radius: 7, fillColor: AMBER, fillOpacity: 0.22 }).addTo(group)
        L.circleMarker(ll, { ...base, radius: 2.8, fillColor: GOLD, fillOpacity: 1 }).addTo(group)
      } else {
        L.circleMarker(ll, { ...base, radius: 1.8, fillColor: '#8693a6', fillOpacity: 0.3 }).addTo(group)
      }
    }
    group.addTo(map)
    return () => {
      group.remove()
    }
  }, [map, renderer, pois, night, openIds])
  return null
})

export default function MapView({
  location,
  result,
  hovered,
  onHover,
  onPick,
  onMarkerClick,
  pois,
  hint,
  coarseLabel,
  lang,
  night,
  clientTime,
  nightLabel,
  hereLabel,
}: Props) {
  // Смена день/ночь: новый слой плавно проявляется поверх, старый размонтируется после перехода —
  // одновременно грузится и рисуется только один слой тайлов.
  const [showDay, setShowDay] = useState(!night)
  const [showNight, setShowNight] = useState(night)
  const [nightOpacity, setNightOpacity] = useState(night ? 1 : 0)
  useEffect(() => {
    const delay = STATIC ? 0 : 700
    let raf = 0
    let timer = 0
    if (night) {
      setShowNight(true)
      raf = requestAnimationFrame(() => setNightOpacity(1))
      timer = window.setTimeout(() => setShowDay(false), delay)
    } else {
      setShowDay(true)
      setNightOpacity(0)
      timer = window.setTimeout(() => setShowNight(false), delay)
    }
    return () => {
      cancelAnimationFrame(raf)
      window.clearTimeout(timer)
    }
  }, [night])
  // Какие точки «горят» — считаем только при смене времени/списка, не на hover.
  const openIds = useMemo(
    () => (night ? new Set(pois.filter((p) => isOpenAt(p.opening_hours, clientTime) === true).map((p) => p.id)) : null),
    [night, pois, clientTime],
  )
  const recs = result?.recommendations ?? []
  const recPoints = useMemo(() => recs.map((r) => [r.lat, r.lon] as [number, number]), [recs])

  const routeLine = useMemo<[number, number][]>(() => {
    if (!result) return []
    const g = result.route?.geometry
    if (g && g.length > 1) return g
    // Нет геометрии — рисуем прямые отрезки по порядку остановок.
    const stops = result.route?.stops ?? []
    const pts = stops
      .map((id) => recs.find((r) => r.poi_id === id))
      .filter(Boolean)
      .map((r) => [r!.lat, r!.lon] as [number, number])
    return pts.length ? [[location.lat, location.lon], ...pts] : []
  }, [result, recs, location])

  return (
    <div className={`relative isolate h-full w-full ${night ? 'map-night' : ''}`}>
      <MapContainer center={[location.lat, location.lon]} zoom={13} className="h-full w-full" zoomControl={false}>
        {showDay && <TileLayer attribution={TILE_ATTR} url={TILE_URL} maxZoom={19} className={MUTED ? 'tiles-muted' : ''} />}
        {showNight && (
          // Тот же OSM, инвертированный в «тёмный город» (фильтр на контейнере слоя): CARTO Dark Matter требует API-ключ.
          <TileLayer attribution={TILE_ATTR} url={TILE_URL} maxZoom={19} className="tiles-night" opacity={nightOpacity} zIndex={2} />
        )}
        <ZoomControl position="bottomright" />
        <ClickToPick onPick={onPick} />
        <ResizeWatcher />
        <FitTo points={recPoints} location={location} />

        <PoiLayer pois={pois} night={night} openIds={openIds} />

        {routeLine.length > 1 &&
          (night ? (
            // неон: широкое мягкое свечение + яркая сердцевина
            <>
              <Polyline positions={routeLine} pathOptions={{ color: TEAL, weight: 20, opacity: 0.12, lineCap: 'round', lineJoin: 'round' }} />
              <Polyline positions={routeLine} pathOptions={{ color: TEAL, weight: 10, opacity: 0.3, lineCap: 'round', lineJoin: 'round' }} />
              <Polyline positions={routeLine} pathOptions={{ color: '#7df3ff', weight: 3.5, opacity: 1, lineCap: 'round', lineJoin: 'round' }} />
            </>
          ) : (
            <>
              <Polyline positions={routeLine} pathOptions={{ color: '#ffffff', weight: 9, opacity: 1, lineCap: 'round', lineJoin: 'round' }} />
              <Polyline positions={routeLine} pathOptions={{ color: TEAL, weight: 5, opacity: 1, lineCap: 'round', lineJoin: 'round' }} />
            </>
          ))}

        <Circle
          center={[location.lat, location.lon]}
          radius={100}
          pathOptions={{ color: TEAL, weight: 1.5, fillColor: TEAL, fillOpacity: 0.12 }}
        />
        <CircleMarker
          center={[location.lat, location.lon]}
          radius={8}
          pathOptions={{ color: '#ffffff', weight: 3, fillColor: TEAL, fillOpacity: 1 }}
        >
          {/* в shadowPane (ниже маркеров): метки мест всегда поверх подписи */}
          <Tooltip permanent direction="bottom" offset={[0, 10]} className="me-label" interactive={false} pane="shadowPane">
            <span title={coarseLabel}>{hereLabel}</span>
          </Tooltip>
        </CircleMarker>
        {night && <Marker position={[location.lat, location.lon]} icon={meIcon} interactive={false} zIndexOffset={-100} />}

        {recs.map((r, i) => (
          <Marker
            key={r.poi_id}
            position={[r.lat, r.lon]}
            icon={pinIcon(i + 1, hovered === i, r.category, night && r.open_status.state === 'open')}
            zIndexOffset={hovered === i ? 1000 : 0}
            eventHandlers={{
              mouseover: () => onHover(i),
              mouseout: () => onHover(null),
              click: () => onMarkerClick(i),
            }}
          >
            <Tooltip direction="top" offset={[0, -20]}>
              {r.name}
              <span className="ml-1 font-normal text-ink-400">· {CATEGORY_LABELS[r.category]?.[lang] ?? r.category}</span>
            </Tooltip>
          </Marker>
        ))}
      </MapContainer>

      <div className="pointer-events-none absolute left-3 top-3 z-[500] flex flex-col items-start gap-2">
        <div className="map-pill inline-flex items-center gap-2 rounded-full bg-white px-3.5 py-2 text-[13px] font-medium text-ink-700 shadow-[0_2px_10px_rgb(11_37_69/0.12)]">
          <MousePointerClick className="h-4 w-4 text-teal-600" strokeWidth={1.8} />
          {hint}
        </div>
        {night && (
          <div className="rise inline-flex items-center gap-2 rounded-full bg-ink-950/85 px-3.5 py-2 text-[13px] font-medium text-sun-100 shadow-[0_0_18px_rgb(254_197_12/0.25)]">
            <Moon className="h-4 w-4 text-sun-500" strokeWidth={1.8} />
            {nightLabel}
          </div>
        )}
      </div>
    </div>
  )
}
