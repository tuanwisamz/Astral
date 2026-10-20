// The one source for hazard colour, icon and label (T3.2). Used by markers, charts,
// filter chips and the legend. Must match /meta/config on the backend.

export type HazardType = 'POTHOLE' | 'FALLEN_TREE' | 'SINKHOLE'
export type IncidentStatus =
  | 'REPORTED'
  | 'VERIFIED'
  | 'ASSIGNED'
  | 'MITIGATED'
  | 'RESOLVED'
  | 'REJECTED'
  | 'DUPLICATE'

export const HAZARD_TYPES: HazardType[] = ['POTHOLE', 'FALLEN_TREE', 'SINKHOLE']

export const HAZARDS: Record<HazardType, { color: string; labelKey: string; glyph: string }> = {
  // Circle with a crack: grey needs the white outline to stand out on the map.
  POTHOLE: {
    color: '#6B7280',
    labelKey: 'hazard.POTHOLE',
    glyph: '<path d="M9 7 l2 3 -2 2 3 3" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/>',
  },
  FALLEN_TREE: {
    color: '#16A34A',
    labelKey: 'hazard.FALLEN_TREE',
    glyph: '<path d="M12 6 l4 6 h-2.5 l3 4 h-9 l3 -4 h-2.5z" fill="#fff"/><rect x="11.2" y="16" width="1.6" height="3" fill="#fff"/>',
  },
  // Inverted triangle (a hole), so green vs brown is never the only cue.
  SINKHOLE: {
    color: '#8B4513',
    labelKey: 'hazard.SINKHOLE',
    glyph: '<path d="M7 8 h10 l-5 9z" fill="#fff"/>',
  },
}

type Outline = 'dashed' | 'solid' | 'hollow'

export function statusOutline(status: IncidentStatus): Outline {
  if (status === 'REPORTED') return 'dashed'
  if (status === 'MITIGATED') return 'hollow'
  return 'solid'
}

/** SVG markup for a map marker or legend swatch. */
export function hazardSvg(type: HazardType, status: IncidentStatus = 'VERIFIED', size = 28, overdue = false): string {
  const { color, glyph } = HAZARDS[type]
  const outline = statusOutline(status)
  const fill = outline === 'hollow' ? '#ffffff' : color
  const dash = outline === 'dashed' ? 'stroke-dasharray="3 2"' : ''
  const ring = outline === 'hollow' ? color : '#ffffff'
  const body =
    outline === 'hollow' ? glyph.replaceAll('#fff', color) : glyph
  const dot = overdue ? '<circle cx="20" cy="4" r="3.5" fill="#B91C1C" stroke="#fff" stroke-width="1"/>' : ''
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="12" r="10" fill="${fill}" stroke="${ring}" stroke-width="2.2" ${dash}/>
    ${body}${dot}</svg>`
}
