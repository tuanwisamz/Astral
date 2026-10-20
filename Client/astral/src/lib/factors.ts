// Model factors arrive as {feature, value, direction}; labels live in i18n (EN/BM), and some
// values need formatting first (a 0.31 heavy-vehicle share reads as "31%").
import type { TFunction } from 'i18next'

import { formatNumber } from './format'

const PERCENT = new Set(['heavy_pct', 'tree_cover'])
const THOUSANDS = new Set(['adt_k'])

export interface Factor {
  feature: string
  value: number
  direction: 'up' | 'down'
}

export function factorLabel(f: Factor, t: TFunction): string {
  let value: string
  if (PERCENT.has(f.feature)) value = `${Math.round(f.value * 100)}%`
  else if (THOUSANDS.has(f.feature)) value = formatNumber(Math.round(f.value * 1000))
  else value = formatNumber(f.value)
  const key = `factor.${f.feature}`
  const label = t(key, { value, defaultValue: '' })
  return label || t('factor.generic', { name: f.feature.replaceAll('_', ' '), value })
}
