import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { useApi } from '../app/auth'
import { buttonClass } from '../components/ui/Button'
import { HazardIcon } from '../components/ui/HazardIcon'
import { EmptyState, ErrorBox, Loading } from '../components/ui/Status'
import { formatRelative } from '../lib/format'
import { HAZARDS, type HazardType, type IncidentStatus } from '../lib/hazards'

interface Mine {
  items: { ref_no: string; hazard_type: HazardType; status: IncidentStatus; road_name: string | null; reported_at: string }[]
  total: number
}

export default function MyReports() {
  const { t } = useTranslation()
  const api = useApi()
  const q = useQuery({ queryKey: ['my-reports'], queryFn: () => api<Mine>('/reports/mine') })

  if (q.isPending) return <div className="mx-auto max-w-2xl p-6"><Loading /></div>
  if (q.isError) return <div className="mx-auto max-w-2xl p-6"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div>
  if (q.data.items.length === 0) {
    return (
      <div className="mx-auto max-w-2xl px-4">
        <EmptyState title={t('placeholder.myReportsTitle')} body={t('placeholder.myReportsBody')}
          action={<Link to="/report" className={buttonClass('primary')}>{t('nav.report')}</Link>} />
      </div>
    )
  }
  return (
    <div className="mx-auto max-w-2xl px-4 py-8">
      <h1 className="text-2xl font-semibold">{t('nav.myReports')}</h1>
      <ul className="mt-6 border-y border-hairline bg-kerb">
        {q.data.items.map((r) => (
          <li key={r.ref_no} className="border-b border-hairline last:border-b-0">
            <Link to={`/report/${r.ref_no}`} className="flex min-h-16 items-center gap-3 px-4 py-3 hover:bg-concrete">
              <HazardIcon type={r.hazard_type} status={r.status} size={26} />
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{t(HAZARDS[r.hazard_type].labelKey)}, {r.road_name ?? t('common.unnamedRoad')}</span>
                <span className="block text-sm text-road">{r.ref_no}, {formatRelative(r.reported_at)}</span>
              </span>
              <span className="text-sm font-semibold">{t(`status.${r.status}`)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}
