import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'

import { useApi } from '../app/auth'
import { buttonClass } from '../components/ui/Button'
import { HazardLabel } from '../components/ui/HazardIcon'
import { RoutePlate } from '../components/ui/RoutePlate'
import { ErrorBox, Loading } from '../components/ui/Status'
import { formatDateTime, formatRelative } from '../lib/format'
import type { IncidentStatus } from '../lib/hazards'
import type { ReportStatus as Status } from '../lib/types'

// Detect → Act, mirrored in the lifecycle stepper (spec §9.2 Conceptual model).
const STEPS: IncidentStatus[] = ['REPORTED', 'VERIFIED', 'ASSIGNED', 'MITIGATED', 'RESOLVED']

export default function ReportStatus() {
  const { t } = useTranslation()
  const api = useApi()
  const { ref } = useParams()
  const q = useQuery({ queryKey: ['report', ref], queryFn: () => api<Status>(`/reports/${ref}`), refetchInterval: 30_000 })

  if (q.isPending) return <div className="mx-auto max-w-lg p-6"><Loading /></div>
  if (q.isError) return <div className="mx-auto max-w-lg p-6"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div>
  const r = q.data
  const closed = r.status === 'REJECTED' || r.status === 'DUPLICATE'
  const reached = new Map(r.timeline.map((e) => [e.status, e.at]))
  const current = STEPS.indexOf(r.status)

  return (
    <div className="mx-auto max-w-lg px-4 py-8">
      <p className="text-sm text-road">{t('tracking.reportRef')}</p>
      <h1 className="font-condensed text-4xl font-semibold tabular">{r.ref_no}</h1>
      <p className="mt-2 flex flex-wrap items-center gap-2">
        <HazardLabel type={r.hazard_type} />
        <span className="text-road">{t('drawer.reportedAt', { when: formatRelative(r.reported_at) })}</span>
      </p>
      <p className="mt-3 flex items-center gap-2">
        <RoutePlate roadClass={r.road_class} routeRef={r.road_ref} />
        <span className="font-condensed text-lg font-semibold">{r.road_name ?? t('common.unnamedRoad')}</span>
      </p>
      <p className="mt-1 text-sm text-road">{t('tracking.handledBy', { owner: r.owner, maintainer: r.maintainer })}</p>

      {closed ? (
        <p role="status" className="mt-6 border-l-4 border-hairline pl-3">{t(`tracking.closed.${r.status}`)}</p>
      ) : (
        <ol className="mt-8 space-y-0" aria-label={t('tracking.progress')}>
          {STEPS.map((s, i) => {
            const done = i <= current
            const at = reached.get(s)
            return (
              <li key={s} className="relative flex gap-4 pb-6 last:pb-0">
                {i < STEPS.length - 1 && <span aria-hidden="true" className={`absolute top-6 left-[11px] h-full w-0.5 ${i < current ? 'bg-asphalt' : 'bg-hairline'}`} />}
                <span aria-hidden="true" className={`relative z-10 mt-0.5 h-6 w-6 shrink-0 rounded-full border-2 ${done ? 'border-asphalt bg-asphalt' : 'border-hairline bg-kerb'} ${i === current ? 'ring-4 ring-marking' : ''}`} />
                <div>
                  <p className={done ? 'font-semibold' : 'text-road'}>
                    {t(`tracking.step.${s}`)}
                    <span className="sr-only">{done ? `, ${t('tracking.done')}` : `, ${t('tracking.notYet')}`}</span>
                  </p>
                  {at && <p className="text-sm text-road">{formatDateTime(at)}</p>}
                  {i === current && r.sla_due_at && s !== 'RESOLVED' && (
                    <p className="text-sm text-road">{t('tracking.dueBy', { when: formatRelative(r.sla_due_at) })}</p>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      )}
      {r.confirmations > 1 && <p className="mt-6 text-sm text-road">{t('tracking.others', { count: r.confirmations - 1 })}</p>}
      <div className="mt-8 flex flex-col gap-3 sm:flex-row">
        <Link to="/my-reports" className={buttonClass('secondary')}>{t('nav.myReports')}</Link>
        <Link to="/report" className={buttonClass('quiet')}>{t('report.another')}</Link>
      </div>
    </div>
  )
}
