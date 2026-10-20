import { useTranslation } from 'react-i18next'

import type { Component, PriorityItem } from '../../lib/types'

// Cool colours only, so score parts never look like a hazard (grey/green/brown), an overdue
// state (red) or an action (yellow). The legend and the bar's label carry the meaning too.
export const COMPONENT_COLORS: Record<Component, string> = {
  safety: '#1E3A5F',
  usage: '#3A6EA5',
  severity: '#7FB7E6',
  predicted: '#6A4C93',
  recurrence: '#B48EAE',
  criticality: '#4E5D6C',
  sla: '#A3195B',
}

/** The score shown as a sum of visible parts (spec §9.2 Conceptual model). */
export function BreakdownBar({ item }: { item: PriorityItem }) {
  const { t } = useTranslation()
  const parts = Object.entries(item.components) as [Component, PriorityItem['components'][Component]][]
  const label = parts.map(([k, c]) => `${t(`priority.components.${k}`)} ${c.contribution.toFixed(1)}`).join(', ')
  return (
    <div className="flex h-3 w-full max-w-44 gap-px overflow-hidden rounded-sm bg-concrete" role="img" aria-label={label} title={label}>
      {parts.map(([k, c]) => (
        <div key={k} style={{ width: `${c.contribution}%`, background: COMPONENT_COLORS[k] }}
          className={c.estimated ? 'opacity-50' : ''} />
      ))}
    </div>
  )
}
