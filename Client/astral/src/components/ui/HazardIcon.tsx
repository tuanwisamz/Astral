import { useTranslation } from 'react-i18next'

import { HAZARDS, hazardSvg, type HazardType, type IncidentStatus } from '../../lib/hazards'

/** Colour + icon shape + text label: hazard type is never shown by colour alone. */
export function HazardIcon({ type, status, size = 20 }: { type: HazardType; status?: IncidentStatus; size?: number }) {
  return <span className="inline-block shrink-0 leading-none" dangerouslySetInnerHTML={{ __html: hazardSvg(type, status, size) }} />
}

export function HazardLabel({ type, status }: { type: HazardType; status?: IncidentStatus }) {
  const { t } = useTranslation()
  return (
    <span className="inline-flex items-center gap-1.5">
      <HazardIcon type={type} status={status} />
      <span>{t(HAZARDS[type].labelKey)}</span>
    </span>
  )
}
