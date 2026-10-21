// Response shapes from the API (spec-api.md §4). Replace with openapi-typescript output once
// it supports TypeScript 7 (plan §2).
import type { Factor } from './factors'
import type { HazardType, IncidentStatus } from './hazards'

export type RoadClass = 'FEDERAL' | 'STATE' | 'MUNICIPAL' | 'EXPRESSWAY' | 'UNKNOWN'
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'VERY_HIGH'

export interface StateInfo {
  code: string
  name: string
  federal_zone: string
}

export interface District {
  id: string
  name: string
  state: string
}

export interface TopRoad {
  segment_id: number
  name: string | null
  ref: string | null
  road_class: RoadClass
  district: string
  owner: string
  maintainer: string
  score: number
  recommended_action: string | null
  refer_to: string[]
}

export interface DashboardSummary {
  scope: { state: string | null; state_name: string | null; district: string | null; district_name: string | null }
  open_incidents: Record<HazardType, number>
  overdue_sla: number
  active_warnings: number
  high_risk_segments: number
  top_roads: TopRoad[]
}

export interface IncidentProps {
  id: string
  ref_no: string
  hazard_type: HazardType
  severity: number
  status: IncidentStatus
  source: string
  confirmations: number
  segment_id: number
  road_name: string | null
  road_ref: string | null
  road_class: RoadClass
  district: string | null
  owner: string
  maintainer: string
  sla_due_at: string | null
  sla_overdue: boolean
  is_synthetic: boolean
  reported_at: string
  refer_to?: string[]
  allowed_next?: IncidentStatus[]
  description?: string | null
  source_url?: string | null
  has_photo?: boolean
  assigned_agency?: string | null
  ai_suggested?: boolean
  /** Where a public report was made (U3b). Staff only; the name is for officers and admins only. */
  reporter_name?: string | null
  address?: string | null
  landmark?: string | null
  gps?: { lat: number; lng: number; accuracy_m: number } | null
  captured_at?: string | null
}

export interface Feature<G, P> {
  type: 'Feature'
  geometry: G
  properties: P
}

export interface FeatureCollection<G, P> {
  type: 'FeatureCollection'
  features: Feature<G, P>[]
  meta?: { count: number; truncated: boolean; updated_at?: string | null }
}

export type Point = { type: 'Point'; coordinates: [number, number] }
export type LineString = { type: 'LineString'; coordinates: [number, number][] }
export type Polygonal = { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown }

export interface SegmentProps {
  segment_id: number
  name: string | null
  ref: string | null
  road_class: RoadClass
  district: string
  owner: string
  maintainer: string
}

export interface PredictionProps {
  segment_id: number
  name: string | null
  hazard_type: HazardType
  horizon_days: number
  probability: number
  risk_level: RiskLevel
  top_factors: Factor[]
  trained_on_demo_data: boolean
  model_version: string
}

export interface WarningProps {
  id: string
  kind: string
  severity: string
  area: string
  valid_from: string | null
  valid_to: string | null
}

export type Component = 'safety' | 'usage' | 'severity' | 'predicted' | 'recurrence' | 'criticality' | 'sla'

export interface PriorityItem {
  rank: number
  rank_in_district: number
  rank_change?: number | null
  segment_id: number
  name: string | null
  ref: string | null
  road_class: RoadClass
  district: string
  owner: string
  maintainer: string
  score: number
  components: Record<Component, { value: number; contribution: number; estimated: boolean }>
  recommended_action: string | null
  refer_to: string[]
}

export interface PriorityList {
  profile: { id: string | null; name: string; weights: Record<Component, number> }
  items: PriorityItem[]
  total: number
  computed_at: string
}

export interface MetaConfig {
  data_freshness: Record<string, string | null>
  synthetic_data_present: boolean
}

export interface Agency {
  id: string
  name: string | null
  type: string | null
  contact?: Record<string, string> | null
  last_verified?: string | null
  contract_valid_to?: string | null
}

export interface LocateResult {
  segment_id: number
  distance_m: number
  name: string | null
  ref: string | null
  road_class: RoadClass
  district: string
  state: { code: string; name: string }
  owner: Agency
  maintainer: Agency
  jurisdiction_source: string
}

export interface SegmentAnalysis {
  segment_id: number
  name: string | null
  ref: string | null
  road_class: RoadClass
  district: string
  state: { code: string; name: string }
  owner: string
  maintainer: string
  length_km: number
  pothole_frequency: { per_km_per_month: number; recurrence_days: number | null; series: { month: string; count: number }[] }
  traffic: { adt: number; heavy_pct: number | null; adt_source: string; estimated: boolean; congestion_series: { date: string; avg_ratio: number }[] }
  natural_events: {
    flood_available: boolean
    series: { month: string; fallen_tree: number; sinkhole: number; weather_warnings: number; flood_warnings: number | null }[]
  }
  weather: { rain_7d: number | null; rain_30d: number | null; forecast_7d: number | null } | null
  safety: { deaths_3y: number; injuries_3y: number; sources: { type: string; url: string | null }[] }
  predictions: { hazard_type: HazardType; horizon_days: number; probability: number; risk_level: RiskLevel; top_factors: Factor[] }[]
  priority: { score: number; rank_in_district: number; components: PriorityItem['components']; recommended_action: string | null; refer_to: string[] } | null
  geology: { karst: boolean; ex_mining: boolean; tree_cover: number | null }
}

export interface SearchResult {
  segment_id: number
  name: string | null
  ref: string | null
  road_class: RoadClass
  district: string
  owner: string
  state: { code: string; name: string }
  segments: number
  length_km: number
}

export interface ZoneSummary {
  zone: { id: string; type: string; name: string; state: string }
  open_incidents: Record<HazardType, number>
  overdue_sla: number
  high_risk_segments: number
  segments: number
  avg_top_priority: number | null
  top_roads: { segment_id: number; name: string | null; ref: string | null; road_class: RoadClass; owner: string; score: number; recommended_action: string | null }[]
  agencies: string[]
}

export interface ReportResult {
  ref_no: string
  status: IncidentStatus
  merged_into: string | null
  confirmations?: number
  segment: { id: number; name: string | null; ref: string | null; road_class: RoadClass }
  responsible: { owner: string; maintainer: string }
  sla_due_at?: string | null
}

export interface PhotoAnalysis {
  analysis_id: string
  is_road_hazard: boolean
  suggested_type: HazardType | null
  suggested_severity: number
  confidence: number
  uncertain: boolean
  reasons: string[]
  privacy_flags: { faces_visible: boolean; plates_visible: boolean }
  nearest_road: { segment_id: number; name: string | null; ref: string | null; road_class: RoadClass; distance_m: number }
}

export interface ReportStatus {
  ref_no: string
  hazard_type: HazardType
  status: IncidentStatus
  road_name: string | null
  road_ref: string | null
  road_class: RoadClass
  owner: string
  maintainer: string
  sla_due_at: string | null
  reported_at: string
  confirmations: number
  timeline: { status: IncidentStatus; at: string }[]
}

export interface ModelCard {
  models: {
    hazard_type: HazardType
    version: string
    algorithm: string
    trained_at: string | null
    training_rows: number
    synthetic_share: number | null
    metrics: Record<string, number | string>
    features: string[]
    limitations: string
  }[]
}
