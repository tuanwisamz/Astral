import { useTranslation } from 'react-i18next'

import { HAZARD_TYPES } from '../../lib/hazards'
import { HazardIcon, HazardLabel } from '../ui/HazardIcon'

function OutlineKey() {
  const { t } = useTranslation()
  return (
    <ul className="space-y-1 text-xs text-road">
      <li className="flex items-center gap-2"><HazardIcon type="POTHOLE" status="REPORTED" size={16} />{t('outline.dashed')}</li>
      <li className="flex items-center gap-2"><HazardIcon type="POTHOLE" status="VERIFIED" size={16} />{t('outline.solid')}</li>
      <li className="flex items-center gap-2"><HazardIcon type="POTHOLE" status="MITIGATED" size={16} />{t('outline.hollow')}</li>
      <li className="flex items-center gap-2">
        <span className="mx-[3px] inline-block h-2.5 w-2.5 rounded-full bg-overdue" />{t('outline.overdue')}
      </li>
    </ul>
  )
}

/**
 * The hazard key is always visible (spec §9.1 Memory). On a phone the outline key folds away
 * so the legend doesn't cover a third of the map; on wider screens everything shows.
 */
export function Legend({ mode, roadHint }: { mode: 'current' | 'prediction'; roadHint: boolean }) {
  const { t } = useTranslation()
  const detail = mode === 'current' ? <OutlineKey /> : <p className="text-xs text-road">{t('map.risk')}</p>
  return (
    <section aria-label={t('map.legend')}
      className="absolute bottom-4 left-4 z-[1000] max-w-[calc(100%-2rem)] rounded border border-hairline bg-kerb/95 p-3 text-sm md:w-60">
      <ul className="flex flex-wrap gap-x-4 gap-y-1.5 md:block md:space-y-1.5">
        {HAZARD_TYPES.map((h) => (
          <li key={h}><HazardLabel type={h} /></li>
        ))}
      </ul>
      <details className="mt-2 border-t border-hairline pt-2 md:hidden">
        <summary className="flex min-h-11 cursor-pointer items-center text-xs font-medium">{t('map.legendMore')}</summary>
        {detail}
      </details>
      <div className="mt-3 hidden border-t border-hairline pt-3 md:block">{detail}</div>
      {roadHint && <p className="mt-3 hidden border-t border-hairline pt-3 text-xs text-road md:block">{t('map.roadHint')}</p>}
    </section>
  )
}
