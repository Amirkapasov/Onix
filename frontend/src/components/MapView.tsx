import { useEffect, useMemo } from 'react'
import { Circle, CircleMarker, MapContainer, Marker, Polyline, TileLayer, Tooltip, useMap, useMapEvents } from 'react-leaflet'
import L from 'leaflet'
import type { LatLon, Poi, RecommendResponse } from '../types'

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
}

function numberIcon(n: number, active: boolean) {
  return L.divIcon({
    className: '',
    html: `<div class="rec-marker${active ? ' rec-marker--active' : ''}"><span>${n}</span></div>`,
    iconSize: [40, 48],
    iconAnchor: [20, 46],
  })
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
    if (points.length === 0) {
      if (STATIC) map.setView([location.lat, location.lon], Math.max(map.getZoom(), 14), { animate: false })
      else map.flyTo([location.lat, location.lon], Math.max(map.getZoom(), 14), { duration: 0.6 })
      return
    }
    const b = L.latLngBounds([[location.lat, location.lon], ...points])
    if (STATIC) map.fitBounds(b, { padding: [60, 60], maxZoom: 16, animate: false })
    else map.flyToBounds(b, { padding: [60, 60], maxZoom: 16, duration: 0.8 })
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

export default function MapView({ location, result, hovered, onHover, onPick, onMarkerClick, pois, hint, coarseLabel }: Props) {
  const recs = result?.recommendations ?? []
  const recPoints = useMemo(() => recs.map((r) => [r.lat, r.lon] as [number, number]), [recs])

  const routeLine = useMemo<[number, number][]>(() => {
    if (!result) return []
    const g = result.route?.geometry
    if (g && g.length > 1) return g
    // Нет геометрии — рисуем прямые отрезки по порядку остановок.
    const stops = result.route?.stops ?? recs.map((r) => r.poi_id)
    const pts = stops
      .map((id) => recs.find((r) => r.poi_id === id))
      .filter(Boolean)
      .map((r) => [r!.lat, r!.lon] as [number, number])
    return pts.length ? [[location.lat, location.lon], ...pts] : []
  }, [result, recs, location])

  return (
    <div className="relative h-full w-full">
      <MapContainer
        center={[location.lat, location.lon]}
        zoom={13}
        className="h-full w-full"
        zoomControl={false}
        attributionControl
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />
        <ClickToPick onPick={onPick} />
        <ResizeWatcher />
        <FitTo points={recPoints} location={location} />

        {pois.map((p) => (
          <CircleMarker
            key={p.id}
            center={[p.lat, p.lon]}
            radius={3}
            pathOptions={{ color: '#64748b', weight: 0, fillOpacity: 0.45 }}
          >
            <Tooltip direction="top">{p.name}</Tooltip>
          </CircleMarker>
        ))}

        {routeLine.length > 1 && (
          <>
            <Polyline positions={routeLine} pathOptions={{ color: '#ffffff', weight: 9, opacity: 0.9 }} />
            <Polyline positions={routeLine} pathOptions={{ color: '#0a8fd1', weight: 5, dashArray: '2 10', lineCap: 'round' }} />
          </>
        )}

        <Circle
          center={[location.lat, location.lon]}
          radius={100}
          pathOptions={{ color: '#0a8fd1', weight: 2, fillColor: '#38bdf8', fillOpacity: 0.18 }}
        />
        <CircleMarker
          center={[location.lat, location.lon]}
          radius={8}
          pathOptions={{ color: '#ffffff', weight: 3, fillColor: '#0a8fd1', fillOpacity: 1 }}
        >
          <Tooltip direction="bottom" offset={[0, 8]}>{coarseLabel}</Tooltip>
        </CircleMarker>

        {recs.map((r, i) => (
          <Marker
            key={r.poi_id}
            position={[r.lat, r.lon]}
            icon={numberIcon(i + 1, hovered === i)}
            zIndexOffset={hovered === i ? 1000 : 0}
            eventHandlers={{
              mouseover: () => onHover(i),
              mouseout: () => onHover(null),
              click: () => onMarkerClick(i),
            }}
          >
            <Tooltip direction="top" offset={[0, -44]}>{r.name}</Tooltip>
          </Marker>
        ))}
      </MapContainer>

      <div className="pointer-events-none absolute left-3 top-3 z-[500] rounded-full bg-white/90 px-4 py-2 text-sm font-medium text-slate-700 shadow-md backdrop-blur">
        👆 {hint}
      </div>
    </div>
  )
}
