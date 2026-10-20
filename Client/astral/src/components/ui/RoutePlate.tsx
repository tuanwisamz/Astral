import { useTranslation } from 'react-i18next'

import type { RoadClass } from '../../lib/types'

// The signature element (DESIGN.md): plate shape shows road class, so class never
// depends on colour alone. Municipal roads have no route number and get no plate.
const PLATE: Partial<Record<RoadClass, string>> = {
  FEDERAL: 'bg-asphalt text-kerb border-2 border-asphalt',
  STATE: 'bg-kerb text-asphalt border-2 border-asphalt',
  EXPRESSWAY: 'bg-asphalt text-kerb border-2 border-asphalt shadow-[inset_0_0_0_1.5px_var(--color-kerb)]',
  UNKNOWN: 'bg-kerb text-road border-2 border-dashed border-road',
}

// The same three shapes inverted for the asphalt panel: solid, outlined, double rule.
const PLATE_ON_DARK: Partial<Record<RoadClass, string>> = {
  FEDERAL: 'bg-kerb text-asphalt border-2 border-kerb',
  STATE: 'bg-asphalt text-kerb border-2 border-kerb',
  EXPRESSWAY: 'bg-kerb text-asphalt border-2 border-kerb shadow-[inset_0_0_0_1.5px_var(--color-asphalt)]',
}

export function plateLabel(roadClass: RoadClass, ref: string | null): string | null {
  if (!ref) return null
  // OSM stores federal refs as bare numbers; show them the way JKR writes them.
  return roadClass === 'FEDERAL' && /^\d/.test(ref) ? `FT${ref}` : ref
}

export function RoutePlate({
  roadClass,
  routeRef,
  onDark = false,
}: {
  roadClass: RoadClass
  routeRef: string | null
  onDark?: boolean
}) {
  const { t } = useTranslation()
  const label = plateLabel(roadClass, routeRef)
  const style = (onDark ? PLATE_ON_DARK : PLATE)[roadClass]
  if (!label || !style) return null
  return (
    <span
      className={`inline-flex h-6 min-w-11 shrink-0 items-center justify-center rounded-[3px] px-1.5 font-condensed text-xs font-semibold tracking-wide ${style}`}
      title={t(`roadClass.${roadClass}`)}
    >
      <span className="sr-only">{t(`roadClass.${roadClass}`)} </span>
      {label}
    </span>
  )
}
