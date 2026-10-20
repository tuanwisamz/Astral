import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { useApi, type Role } from '../app/auth'
import { Button } from '../components/ui/Button'
import { HazardLabel } from '../components/ui/HazardIcon'
import { DemoBadge, ErrorBox, Loading } from '../components/ui/Status'
import { useToast } from '../components/ui/Toast'
import { formatNumber, formatRelative } from '../lib/format'
import type { ModelCard, StateInfo } from '../lib/types'

interface AdminUser {
  clerk_id: string
  email: string | null
  role: Role
  state_code: string | null
}

const ROLES: Role[] = ['public', 'officer', 'viewer', 'admin']
const SCOPED: Role[] = ['officer', 'viewer']
const control = 'min-h-11 rounded border border-road bg-kerb px-2'

// Registering only ever creates public accounts; this is where staff get access (spec §3, D9).
function UserRow({ user, states }: { user: AdminUser; states: StateInfo[] }) {
  const { t } = useTranslation()
  const api = useApi()
  const qc = useQueryClient()
  const toast = useToast()
  const [role, setRole] = useState<Role>(user.role)
  const [state, setState] = useState(user.state_code ?? '')
  const needsState = SCOPED.includes(role) && !state
  const save = useMutation({
    mutationFn: () =>
      api<AdminUser>(`/admin/users/${user.clerk_id}`, {
        method: 'PATCH',
        body: SCOPED.includes(role) ? { role, state_code: state } : { role },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['admin-users'] })
      toast(t('admin.saved', { email: user.email ?? user.clerk_id }))
    },
  })
  const changed = role !== user.role || (SCOPED.includes(role) && state !== (user.state_code ?? ''))

  return (
    <li className="grid gap-3 border-b border-hairline px-4 py-4 last:border-b-0 md:grid-cols-[minmax(0,1fr)_12rem_12rem_auto] md:items-center">
      <span className="truncate font-medium">{user.email ?? user.clerk_id}</span>
      <label className="flex flex-col gap-1 text-sm md:contents">
        <span className="md:sr-only">{t('admin.role')}</span>
        <select className={control} value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {ROLES.map((r) => <option key={r} value={r}>{t(`admin.roles.${r}`)}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-sm md:contents">
        <span className="md:sr-only">{t('admin.state')}</span>
        <select className={control} value={state} disabled={!SCOPED.includes(role)}
          onChange={(e) => setState(e.target.value)} aria-invalid={needsState || undefined}>
          <option value="">{t('admin.noState')}</option>
          {states.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
        </select>
      </label>
      <div>
        <Button variant={changed ? 'primary' : 'secondary'} disabled={!changed || needsState || save.isPending}
          onClick={() => save.mutate()}>
          {t('admin.save')}
        </Button>
        {needsState && <p className="mt-1 text-sm text-overdue">{t('admin.needsState')}</p>}
        {save.isError && <div className="mt-2"><ErrorBox error={save.error} /></div>}
      </div>
    </li>
  )
}

export default function Admin() {
  const { t } = useTranslation()
  const api = useApi()
  const [draft, setDraft] = useState('')
  const [query, setQuery] = useState('')
  const states = useQuery({ queryKey: ['states'], queryFn: () => api<StateInfo[]>('/meta/states') })
  const users = useQuery({
    queryKey: ['admin-users', query],
    queryFn: () => api<{ items: AdminUser[] }>('/admin/users', { params: { q: query } }),
    retry: false,
  })
  const search = (e: FormEvent) => {
    e.preventDefault()
    setQuery(draft.trim())
  }

  return (
    <div className="max-w-5xl px-4 py-8 sm:px-8">
      <h1 className="text-2xl font-semibold">{t('admin.title')}</h1>
      <section className="mt-8">
        <h2 className="text-xl font-semibold">{t('admin.usersTitle')}</h2>
        <p className="mt-1 max-w-prose text-road">{t('admin.usersBody')}</p>
        <form onSubmit={search} className="mt-5 flex max-w-md gap-2">
          <label htmlFor="user-search" className="sr-only">{t('admin.search')}</label>
          <input id="user-search" type="search" placeholder={t('admin.search')} value={draft}
            onChange={(e) => setDraft(e.target.value)} className={`${control} min-w-0 flex-1 px-3`} />
          <Button type="submit">{t('admin.searchButton')}</Button>
        </form>
        <div className="mt-5">
          {users.isPending && <Loading />}
          {users.isError && <ErrorBox error={users.error} onRetry={() => users.refetch()} />}
          {users.data && (users.data.items.length === 0 ? (
            <p className="text-road">{t('admin.empty')}</p>
          ) : (
            <ul className="border-y border-hairline bg-kerb">
              {users.data.items.map((u) => <UserRow key={u.clerk_id} user={u} states={states.data ?? []} />)}
            </ul>
          ))}
        </div>
      </section>
      <DataSources />
      <ModelCardSection />
      <Agencies />
    </div>
  )
}

interface Sources {
  jobs: { job: string; last_run: string | null; status: string; items: number; quota_used: number; error: string | null }[]
  quotas: Record<string, { used: number; limit: number | string }>
}

/** Job health and free-tier quota use (T5.6, NFR-01): the "RM0" evidence for the demo. */
function DataSources() {
  const { t } = useTranslation()
  const api = useApi()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['data-sources'], queryFn: () => api<Sources>('/admin/data-sources'), refetchInterval: 60_000 })
  const run = useMutation({
    mutationFn: (job: string) => api<{ status: string; items: number }>(`/admin/jobs/${job}`, { method: 'POST' }),
    onSuccess: (r, job) => { void qc.invalidateQueries({ queryKey: ['data-sources'] }); toast(t('admin.ran', { job, status: r.status, items: r.items })) },
  })
  return (
    <section className="mt-12">
      <h2 className="text-xl font-semibold">{t('admin.sourcesTitle')}</h2>
      <p className="mt-1 max-w-prose text-road">{t('admin.sourcesBody')}</p>
      {q.isPending && <div className="mt-4"><Loading /></div>}
      {q.isError && <div className="mt-4"><ErrorBox error={q.error} onRetry={() => q.refetch()} /></div>}
      {q.data && (
        <>
          <dl className="mt-4 flex flex-wrap gap-8">
            {Object.entries(q.data.quotas).map(([k, v]) => (
              <div key={k} className="flex flex-col">
                <dt className="order-2 text-sm text-road">{t(`admin.quota.${k}`, { defaultValue: k })}</dt>
                <dd className="order-1 font-condensed text-2xl font-semibold tabular">
                  {formatNumber(v.used)}<span className="text-base text-road">{typeof v.limit === 'number' ? ` / ${formatNumber(v.limit)}` : ''}</span>
                </dd>
              </div>
            ))}
          </dl>
          <ul className="mt-4 border-y border-hairline bg-kerb">
            {q.data.jobs.map((j) => (
              <li key={j.job} className="grid gap-2 border-b border-hairline px-4 py-3 last:border-b-0 md:grid-cols-[9rem_6rem_minmax(0,1fr)_auto] md:items-center">
                <span className="font-semibold">{t(`admin.jobs.${j.job}`, { defaultValue: j.job })}</span>
                <span className={j.status === 'ERROR' ? 'font-semibold text-overdue' : j.status === 'OK' ? '' : 'text-road'}>{t(`admin.jobStatus.${j.status}`, { defaultValue: j.status })}</span>
                <span className="text-sm text-road">
                  {j.last_run ? t('admin.lastRun', { when: formatRelative(j.last_run), items: j.items }) : t('admin.neverRun')}
                  {j.error && <span className="block break-words">{j.error}</span>}
                </span>
                <Button onClick={() => run.mutate(j.job)} disabled={run.isPending}>{t('admin.runNow')}</Button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

/** FR-PRD-03: version, data, metrics, and a warning when trained on demo data. */
function ModelCardSection() {
  const { t } = useTranslation()
  const api = useApi()
  const q = useQuery({ queryKey: ['model-card'], queryFn: () => api<ModelCard>('/predictions/model-card') })
  return (
    <section className="mt-12" id="model-card">
      <h2 className="text-xl font-semibold">{t('admin.modelTitle')}</h2>
      {q.isError && <div className="mt-4"><ErrorBox error={q.error} /></div>}
      {q.data && q.data.models.length === 0 && <p className="mt-2 text-road">{t('admin.noModels')}</p>}
      <ul className="mt-4 space-y-4">
        {q.data?.models.map((m) => (
          <li key={m.version} className="border-l-4 border-hairline bg-kerb p-4">
            <p className="flex flex-wrap items-center gap-2 font-semibold">
              <HazardLabel type={m.hazard_type} />
              {(m.synthetic_share ?? 0) >= 0.5 && <DemoBadge />}
            </p>
            <p className="mt-1 text-sm">{m.algorithm}</p>
            <p className="text-sm text-road">{m.version}, {t('admin.trained', { when: formatRelative(m.trained_at), rows: formatNumber(m.training_rows) })}</p>
            <dl className="mt-3 flex flex-wrap gap-6 text-sm">
              {[['pr_auc', 'PR-AUC'], ['baseline_pr_auc', t('admin.baselinePrAuc')], ['brier', 'Brier'], ['baseline_brier', t('admin.baselineBrier')]]
                .filter(([k]) => m.metrics[k] !== undefined)
                .map(([k, label]) => (
                  <div key={k} className="flex flex-col"><dt className="order-2 text-road">{label}</dt><dd className="order-1 font-semibold tabular">{m.metrics[k]}</dd></div>
                ))}
            </dl>
            <p className="mt-3 max-w-prose text-sm">{m.limitations}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}

interface AgencyRow { id: string; type: string; name: string; state_code: string | null; last_verified: string | null; contract_valid_to: string | null; segments: number }

/** The editable agency table with a "last verified" date (spec §2: contracts are in transition). */
function Agencies() {
  const { t } = useTranslation()
  const api = useApi()
  const qc = useQueryClient()
  const toast = useToast()
  const q = useQuery({ queryKey: ['admin-agencies'], queryFn: () => api<AgencyRow[]>('/admin/agencies', { params: { type: 'FED_MAINT_CONCESSIONAIRE' } }) })
  const verify = useMutation({
    mutationFn: (id: string) => api(`/admin/agencies/${id}`, { method: 'PATCH', body: { last_verified: new Date().toISOString().slice(0, 10) } }),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ['admin-agencies'] }); toast(t('admin.verified')) },
  })
  return (
    <section className="mt-12">
      <h2 className="text-xl font-semibold">{t('admin.agenciesTitle')}</h2>
      <p className="mt-1 max-w-prose text-road">{t('admin.agenciesBody')}</p>
      {q.isError && <div className="mt-4"><ErrorBox error={q.error} /></div>}
      <ul className="mt-4 border-y border-hairline bg-kerb">
        {q.data?.map((a) => (
          <li key={a.id} className="grid gap-2 border-b border-hairline px-4 py-3 last:border-b-0 md:grid-cols-[minmax(0,1fr)_10rem_auto] md:items-center">
            <span><span className="font-semibold">{a.name}</span><span className="block text-sm text-road">{t('admin.segmentsCount', { count: a.segments })}{a.contract_valid_to ? `, ${t('admin.contractTo', { date: a.contract_valid_to })}` : ''}</span></span>
            <span className={a.last_verified ? 'text-sm' : 'text-sm font-semibold text-overdue'}>{a.last_verified ? t('admin.verifiedOn', { date: a.last_verified }) : t('admin.notVerified')}</span>
            <Button onClick={() => verify.mutate(a.id)} disabled={verify.isPending}>{t('admin.markVerified')}</Button>
          </li>
        ))}
      </ul>
    </section>
  )
}
