import 'leaflet.markercluster'
import 'leaflet.markercluster/dist/MarkerCluster.css'

import L from 'leaflet'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { GeoJSON, Polyline, useMap, useMapEvents } from 'react-leaflet'

import { HAZARD_TYPES, HAZARDS, hazardSvg, type HazardType } from '../../lib/hazards'
import type {
  FeatureCollection,
  IncidentProps,
  LineString,
  Point,
  Polygonal,
  PredictionProps,
  RoadClass,
  SegmentProps,
  WarningProps,
} from '../../lib/types'

const toLatLng = (coords: [number, number][]) => coords.map(([lng, lat]) => [lat, lng] as [number, number])

/** Reports the visible area and zoom, 300 ms after panning stops (architechture.md §4.1). */
export function BboxWatcher({ onChange }: { onChange: (bbox: string, zoom: number) => void }) {
  const map = useMap()
  useEffect(() => {
    let timer: number | undefined
    const report = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(() => onChange(map.getBounds().toBBoxString(), map.getZoom()), 300)
    }
    report()
    map.on('moveend', report)
    return () => {
      window.clearTimeout(timer)
      map.off('moveend', report)
    }
  }, [map, onChange])
  return null
}

export function MapClick({ onClick }: { onClick: (lat: number, lng: number, zoom: number) => void }) {
  const map = useMapEvents({ click: (e) => onClick(e.latlng.lat, e.latlng.lng, map.getZoom()) })
  return null
}

/** Moves the map to show a road (from ?segment= or the assistant's highlights). */
export function FitTo({ coords }: { coords: [number, number][] | null }) {
  const map = useMap()
  useEffect(() => {
    if (coords && coords.length) map.fitBounds(L.latLngBounds(toLatLng(coords)), { maxZoom: 16, padding: [40, 40] })
  }, [map, coords])
  return null
}

function pie(counts: Record<HazardType, number>, total: number): string {
  // A small pie of the hazard mix (architechture.md §4.1), with the count in the middle.
  let start = 0
  const stops = HAZARD_TYPES.filter((h) => counts[h]).map((h) => {
    const end = start + (counts[h] / total) * 360
    const s = `${HAZARDS[h].color} ${start}deg ${end}deg`
    start = end
    return s
  })
  const size = total < 10 ? 34 : total < 100 ? 40 : 46
  return `<div style="width:${size}px;height:${size}px;border-radius:50%;background:conic-gradient(${stops.join(',')});
    display:grid;place-items:center;border:2px solid #fff;box-shadow:0 0 0 1px #2E3236">
    <span style="background:#fff;color:#2E3236;border-radius:50%;width:${size - 16}px;height:${size - 16}px;display:grid;
      place-items:center;font:600 12px Barlow Condensed, sans-serif">${total}</span></div>`
}

/** Incident markers, clustered below zoom 13 with leaflet.markercluster through useMap(), not a wrapper. */
export function IncidentLayer({ data, onSelect }: { data: FeatureCollection<Point, IncidentProps>; onSelect: (p: IncidentProps) => void }) {
  const map = useMap()
  const { t } = useTranslation()
  const group = useRef<L.MarkerClusterGroup | null>(null)
  const select = useRef(onSelect)
  useEffect(() => { select.current = onSelect })

  useEffect(() => {
    const g = L.markerClusterGroup({
      disableClusteringAtZoom: 13,
      showCoverageOnHover: false,
      maxClusterRadius: 50,
      iconCreateFunction: (cluster) => {
        const counts = { POTHOLE: 0, FALLEN_TREE: 0, SINKHOLE: 0 } as Record<HazardType, number>
        for (const m of cluster.getAllChildMarkers()) counts[(m.options as { hazard: HazardType }).hazard] += 1
        const total = cluster.getChildCount()
        return L.divIcon({ html: pie(counts, total), className: 'hazard-marker', iconSize: [46, 46] })
      },
    })
    group.current = g
    map.addLayer(g)
    return () => { map.removeLayer(g) }
  }, [map])

  useEffect(() => {
    const g = group.current
    if (!g) return
    g.clearLayers()
    g.addLayers(data.features.map(({ geometry, properties: p }) => {
      const marker = L.marker([geometry.coordinates[1], geometry.coordinates[0]], {
        icon: L.divIcon({ className: 'hazard-marker', html: hazardSvg(p.hazard_type, p.status, 30, p.sla_overdue), iconSize: [30, 30], iconAnchor: [15, 15] }),
        title: `${t(`hazard.${p.hazard_type}`)}, ${t(`status.${p.status}`).toLowerCase()}, ${p.road_name ?? t('common.unnamedRoad')}`,
        keyboard: true,
        hazard: p.hazard_type,
      } as L.MarkerOptions & { hazard: HazardType })
      marker.on('click', (e) => { L.DomEvent.stopPropagation(e); select.current(p) })
      return marker
    }))
  }, [data, t])
  return null
}

// The road layer is asphalt-toned so hazard colours stay the loudest thing on the map;
// class shows in weight and the drawer's route plate, not in hue.
const CLASS_STYLE: Record<RoadClass, { color: string; weight: number }> = {
  EXPRESSWAY: { color: '#2E3236', weight: 6 },
  FEDERAL: { color: '#2E3236', weight: 5 },
  STATE: { color: '#5A6168', weight: 4 },
  MUNICIPAL: { color: '#8A9196', weight: 3 },
  UNKNOWN: { color: '#A9AFB2', weight: 3 },
}

export function SegmentLayer({ data, onSelect }: { data: FeatureCollection<LineString, SegmentProps>; onSelect: (p: SegmentProps) => void }) {
  return (
    <>
      {data.features.map(({ geometry, properties: p }) => {
        const { color, weight } = CLASS_STYLE[p.road_class]
        return (
          <Polyline key={p.segment_id} positions={toLatLng(geometry.coordinates)} pathOptions={{ color, weight, opacity: 0.45 }}
            eventHandlers={{
              click: (e) => { L.DomEvent.stopPropagation(e); onSelect(p) },
              mouseover: (e) => e.target.setStyle({ color: '#F5C400', weight: weight + 3, opacity: 1 }),
              mouseout: (e) => e.target.setStyle({ color, weight, opacity: 0.45 }),
            }} />
        )
      })}
    </>
  )
}

/** Higher risk = thicker, more opaque line (spec §9.2 Mapping). */
export function PredictionLayer({ data, onSelect }: { data: FeatureCollection<LineString, PredictionProps>; onSelect: (p: PredictionProps) => void }) {
  return (
    <>
      {data.features.map(({ geometry, properties: p }) => (
        <Polyline key={`${p.segment_id}-${p.hazard_type}`} positions={toLatLng(geometry.coordinates)}
          pathOptions={{ color: HAZARDS[p.hazard_type].color, weight: 2 + 6 * p.probability, opacity: 0.3 + 0.7 * p.probability }}
          eventHandlers={{ click: (e) => { L.DomEvent.stopPropagation(e); onSelect(p) } }} />
      ))}
    </>
  )
}

/** Roads picked out by the assistant or a link: marking yellow under an asphalt core. */
export function HighlightLayer({ lines }: { lines: [number, number][][] }) {
  return (
    <>
      {lines.map((coords, i) => (
        <Polyline key={i} positions={toLatLng(coords)} pathOptions={{ color: '#F5C400', weight: 12, opacity: 0.9 }} interactive={false} />
      ))}
      {lines.map((coords, i) => (
        <Polyline key={`c${i}`} positions={toLatLng(coords)} pathOptions={{ color: '#2E3236', weight: 4, opacity: 1 }} interactive={false} />
      ))}
    </>
  )
}

export function WarningLayer({ data }: { data: FeatureCollection<Polygonal, WarningProps> }) {
  return (
    <GeoJSON key={data.features.map((f) => f.properties.id).join(',')} data={data as GeoJSON.FeatureCollection}
      style={{ color: '#2E3236', weight: 1.5, dashArray: '6 4', fillColor: '#5A6168', fillOpacity: 0.12 }}
      onEachFeature={(f, layer) => layer.bindTooltip(`${f.properties.kind}`, { sticky: true })} />
  )
}
