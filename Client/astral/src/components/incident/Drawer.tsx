import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { useApi } from '../../app/auth'
import i18n from '../../i18n'
import { factorLabel } from '../../lib/factors'
import { formatDate, formatDateTime, formatRelative } from '../../lib/format'
import type { IncidentStatus } from '../../lib/hazards'
import type { Agency, IncidentProps, LocateResult, PredictionProps, RoadClass, SegmentProps } from '../../lib/types'
import { Button, buttonClass } from '../ui/Button'
import { HazardLabel } from '../ui/HazardIcon'
import { RoutePlate } from '../ui/RoutePlate'
import { DemoBadge, ErrorBox } from '../ui/Status'
import { Term } from '../ui/Term'
import { useToast } from '../ui/Toast'

export type Selection =
  | { kind: 'incident'; props: IncidentProps }
  | { kind: 'segment'; props: SegmentProps }
  | { kind: 'prediction'; props: PredictionProps }
  | { kind: 'road'; props: LocateResult }

// Forward steps in the lifecycle get the primary button; side exits stay secondary.
const FORWARD: IncidentStatus[] = ['VERIFIED', 'ASSIGNED', 'MITIGATED', 'RESOLVED', 'REPORTED']
const list = (items: string[]) => new Intl.ListFormat(i18n.language === 'ms' ? 'ms' : 'en', { type: 'conjunction' }).format(items)

function Row({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_1fr] gap-3 border-b border-hairline py-2.5 text-sm last:border-b-0">
      <dt className="text-road">{label}</dt>
      <dd>{children}</dd>
    </div>
  )
}

function RoadLine({ roadClass, routeRef, name }: { roadClass: RoadClass; routeRef: string | null; name: string | null }) {
  const { t } = useTranslation()
  return (
    <p className="flex flex-wrap items-center gap-2">
      <RoutePlate roadClass={roadClass} routeRef={routeRef} />
      <span className="font-condensed text-lg leading-tight font-semibold">{name ?? t('common.unnamedRoad')}</span>
    </p>
  )
}

function OfficerTools({ inc, onChanged }: { inc: IncidentProps; onChanged: (data: IncidentProps) => void }) {
  const { t } = useTranslation()
  const api = useApi()
  const [note, setNote] = useState('')
  const [photoUrl, setPhotoUrl] = useState<string | null>(null)
  const agencies = useQuery({ queryKey: ['agencies-for-assign'], queryFn: () => api<Agency[]>('/meta/agencies'), staleTime: 300_000 })
  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) => api<IncidentProps>(`/incidents/${inc.id}`, { method: 'PATCH', body }),
    onSuccess: (data) => { onChanged(data); setNote('') },
  })
  const photo = useMutation({
    mutationFn: () => api<{ url: string }>(`/incidents/${inc.id}/photo`),
    onSuccess: (r) => setPhotoUrl(r.url),
  })
  return (
    <section className="mt-6 space-y-4 border-t border-hairline pt-4">
      {inc.has_photo && (photoUrl ? (
        <img src={photoUrl} alt={t('drawer.photoAlt')} className="max-h-64 w-full rounded object-cover" />
      ) : (
        <Button onClick={() => photo.mutate()} disabled={photo.isPending}>{t('drawer.showPhoto')}</Button>
      ))}
      {photo.isError && <ErrorBox error={photo.error} />}
      <label className="block text-sm">
        <span className="font-semibold">{t('drawer.assign')}</span>
        <select className="mt-1 block min-h-11 w-full rounded border border-road bg-kerb px-2" value=""
          onChange={(e) => e.target.value && patch.mutate({ assigned_agency_id: e.target.value })} disabled={patch.isPending}>
          <option value="">{inc.assigned_agency ?? t('drawer.chooseAgency')}</option>
          {agencies.data?.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </label>
      <form onSubmit={(e) => { e.preventDefault(); if (note.trim()) patch.mutate({ note: note.trim() }) }}>
        <label className="block text-sm">
          <span className="font-semibold">{t('drawer.note')}</span>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={2000}
            className="mt-1 block w-full rounded border border-road bg-kerb p-2" />
        </label>
        <Button type="submit" className="mt-2" disabled={!note.trim() || patch.isPending}>{t('drawer.addNote')}</Button>
      </form>
      {patch.isError && <ErrorBox error={patch.error} />}
    </section>
  )
}

/** Who reported it and where they stood (U3b). The API leaves the name out for viewers. */
function ReportedBy({ inc }: { inc: IncidentProps }) {
  const { t } = useTranslation()
  const gps = inc.gps
  return (
    <section className="mt-6">
      <h3 className="mb-1 font-semibold">{t('drawer.reportedBy')}</h3>
      <dl>
        {inc.reporter_name && <Row label={t('drawer.reporterName')}>{inc.reporter_name}</Row>}
        {inc.address && <Row label={t('drawer.address')}>{inc.address}</Row>}
        {inc.landmark && <Row label={t('drawer.landmark')}>{inc.landmark}</Row>}
        {gps && (
          <Row label={t('drawer.gps')}>
            <a href={`https://www.openstreetmap.org/?mlat=${gps.lat}&mlon=${gps.lng}#map=19/${gps.lat}/${gps.lng}`}
              target="_blank" rel="noreferrer" className="tabular underline">
              {gps.lat.toFixed(5)}, {gps.lng.toFixed(5)}
            </a>{' '}
            <span className="text-road">{t('report.gpsAccuracy', { accuracy: Math.round(gps.accuracy_m) })}</span>
          </Row>
        )}
        {inc.captured_at && <Row label={t('drawer.capturedAt')}>{formatDateTime(inc.captured_at)}</Row>}
      </dl>
    </section>
  )
}

function IncidentDetail({ props, staff, canEdit }: { props: IncidentProps; staff: boolean; canEdit: boolean }) {
  const { t } = useTranslation()
  const api = useApi()
  const qc = useQueryClient()
  const toast = useToast()
  // Officer detail adds allowed next steps and referrals; the public sees the map's fields only.
  const q = useQuery({ queryKey: ['incident', props.id], queryFn: () => api<IncidentProps>(`/incidents/${props.id}`), enabled: staff, placeholderData: props })
  const refresh = (data: IncidentProps) => {
    qc.setQueryData(['incident', props.id], data)
    void qc.invalidateQueries({ queryKey: ['map-incidents'] })
  }
  const undo = useMutation({
    mutationFn: () => api<IncidentProps>(`/incidents/${props.id}/undo`, { method: 'POST' }),
    onSuccess: (data) => { refresh(data); toast(t('drawer.undone')) },
    onError: () => toast(t('drawer.undoExpired')),
  })
  const move = useMutation({
    mutationFn: (status: IncidentStatus) => api<IncidentProps>(`/incidents/${props.id}`, { method: 'PATCH', body: { status } }),
    onSuccess: (data, status) => {
      refresh(data)
      toast(t(`drawer.marked.${status}`), { label: t('drawer.undo'), onClick: () => undo.mutate() })
    },
  })
  const inc = q.data ?? props
  const next = [...(inc.allowed_next ?? [])].sort((a, b) => (FORWARD.indexOf(a) + 1 || 99) - (FORWARD.indexOf(b) + 1 || 99))

  return (
    <>
      <div className="flex items-start justify-between gap-3 pr-12">
        <h2 className="text-xl font-semibold"><HazardLabel type={inc.hazard_type} status={inc.status} /></h2>
        {inc.is_synthetic && <DemoBadge />}
      </div>
      <p className="mt-1 text-sm text-road">
        {t('drawer.reportedAt', { when: formatRelative(inc.reported_at) })}
        {inc.source === 'NEWS' && `, ${t('drawer.fromNews')}`}
      </p>
      <div className="mt-4"><RoadLine roadClass={inc.road_class} routeRef={inc.road_ref} name={inc.road_name} /></div>
      <dl className="mt-4">
        <Row label={t('drawer.status')}>{t(`status.${inc.status}`)}</Row>
        <Row label={t('drawer.owner')}>{inc.owner}</Row>
        <Row label={t('drawer.maintainer')}>{inc.maintainer}</Row>
        {inc.refer_to && <Row label={t('drawer.referTo')}>{list(inc.refer_to)}</Row>}
        {inc.assigned_agency && <Row label={t('drawer.assignedTo')}>{inc.assigned_agency}</Row>}
        <Row label={<Term name="SLA">{t('drawer.sla')}</Term>}>
          <span className={inc.sla_overdue ? 'font-semibold text-overdue' : ''}>
            {inc.sla_overdue && `${t('drawer.slaOverdue')}, `}{formatRelative(inc.sla_due_at)}
          </span>
        </Row>
        <Row label={t('drawer.severity', { value: inc.severity })}>{t('drawer.confirmations', { count: inc.confirmations })}</Row>
        {inc.description && <Row label={t('drawer.description')}>{inc.description}</Row>}
        {inc.source_url && <Row label={t('drawer.source')}><a href={inc.source_url} target="_blank" rel="noreferrer" className="underline">{t('drawer.newsLink')}</a></Row>}
      </dl>
      {staff && (inc.reporter_name || inc.address || inc.gps) && <ReportedBy inc={inc} />}
      {staff && (
        <section className="mt-6">
          <h3 className="mb-3 font-semibold">{t('drawer.actions')}</h3>
          {move.isError && <div className="mb-3"><ErrorBox error={move.error} /></div>}
          {!canEdit ? <p className="text-sm text-road">{t('drawer.viewOnly')}</p> : next.length ? (
            <div className="flex flex-wrap gap-2">
              {next.map((s, i) => (
                <Button key={s} variant={i === 0 && FORWARD.includes(s) ? 'primary' : 'secondary'} disabled={move.isPending} onClick={() => move.mutate(s)}>
                  {t(`drawer.mark.${s}`)}
                </Button>
              ))}
            </div>
          ) : <p className="text-sm text-road">{t('drawer.noActions')}</p>}
        </section>
      )}
      {staff && canEdit && <OfficerTools inc={inc} onChanged={refresh} />}
      {staff && <Link to={`/analysis/${inc.segment_id}`} className={buttonClass('quiet', 'mt-4 px-0')}>{t('drawer.openAnalysis')}</Link>}
    </>
  )
}

function SegmentDetail({ p }: { p: SegmentProps }) {
  const { t } = useTranslation()
  return (
    <>
      <div className="pr-12"><RoadLine roadClass={p.road_class} routeRef={p.ref} name={p.name} /></div>
      <dl className="mt-4">
        <Row label={t('drawer.class')}>{t(`roadClass.${p.road_class}`)}</Row>
        <Row label={t('drawer.district')}>{p.district}</Row>
        <Row label={t('drawer.owner')}>{p.owner}</Row>
        <Row label={t('drawer.maintainer')}>{p.maintainer}</Row>
      </dl>
      <Link to={`/analysis/${p.segment_id}`} className={buttonClass('quiet', 'mt-4 px-0')}>{t('drawer.openAnalysis')}</Link>
    </>
  )
}

/** "Who maintains this road?" (FR-MAP-06), for anyone who clicks a road. */
function RoadDetail({ p }: { p: LocateResult }) {
  const { t } = useTranslation()
  const contact = p.owner.contact && Object.entries(p.owner.contact).filter(([k]) => k !== 'note')
  return (
    <>
      <p className="text-sm text-road">{t('drawer.whoMaintains')}</p>
      <div className="mt-1 pr-12"><RoadLine roadClass={p.road_class} routeRef={p.ref} name={p.name} /></div>
      <dl className="mt-4">
        <Row label={t('drawer.class')}>{t(`roadClass.${p.road_class}`)}</Row>
        <Row label={t('drawer.district')}>{p.district}, {p.state.name}</Row>
        <Row label={t('drawer.owner')}>{p.owner.name}</Row>
        <Row label={t('drawer.maintainer')}>
          {p.maintainer.name}
          {p.maintainer.last_verified ? <span className="block text-road">{t('drawer.verifiedOn', { date: formatDate(p.maintainer.last_verified) })}</span>
            : p.maintainer.type?.includes('CONCESSIONAIRE') && <span className="block text-road">{t('drawer.notVerified')}</span>}
        </Row>
        {contact && contact.length > 0 && <Row label={t('drawer.contact')}>{contact.map(([k, v]) => <span key={k} className="block">{v}</span>)}</Row>}
      </dl>
      {p.jurisdiction_source === 'RULE' && <p className="mt-3 text-sm text-road">{t('drawer.ruleBased')}</p>}
    </>
  )
}

function PredictionDetail({ p }: { p: PredictionProps }) {
  const { t } = useTranslation()
  return (
    <>
      <div className="flex items-start justify-between gap-3 pr-12">
        <h2 className="text-xl font-semibold"><HazardLabel type={p.hazard_type} /></h2>
        {p.trained_on_demo_data && <DemoBadge />}
      </div>
      <p className="mt-4 font-condensed text-lg font-semibold">{p.name ?? t('common.unnamedRoad')}</p>
      <dl className="mt-2">
        <Row label={t('drawer.probability', { count: p.horizon_days })}>
          <span className="font-semibold tabular">{Math.round(p.probability * 100)}%</span>, {t(`risk.${p.risk_level}`).toLowerCase()}
        </Row>
      </dl>
      <h3 className="mt-6 mb-2 font-semibold">{t('drawer.topFactors')}</h3>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {p.top_factors.map((f) => <li key={f.feature}>{factorLabel(f, t)}</li>)}
      </ul>
      <Link to={`/analysis/${p.segment_id}`} className={buttonClass('quiet', 'mt-4 px-0')}>{t('drawer.openAnalysis')}</Link>
    </>
  )
}

export function Drawer({ selection, staff, canEdit, onClose }: { selection: Selection; staff: boolean; canEdit: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <aside aria-label={t('drawer.label')}
      className="absolute inset-y-0 right-0 z-[1000] w-full max-w-sm overflow-auto border-l border-hairline bg-kerb p-5 shadow-[-12px_0_32px_-16px_rgba(46,50,54,0.35)]">
      <button type="button" onClick={onClose} aria-label={t('drawer.close')}
        className="absolute top-3 right-3 min-h-11 min-w-11 rounded text-2xl leading-none text-road hover:bg-concrete">×</button>
      {selection.kind === 'incident' && <IncidentDetail key={selection.props.id} props={selection.props} staff={staff} canEdit={canEdit} />}
      {selection.kind === 'segment' && <SegmentDetail p={selection.props} />}
      {selection.kind === 'prediction' && <PredictionDetail p={selection.props} />}
      {selection.kind === 'road' && <RoadDetail p={selection.props} />}
    </aside>
  )
}
