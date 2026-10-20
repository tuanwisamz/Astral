import { useReverification, useUser } from '@clerk/clerk-react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { AUTH_CONFIGURED, useApi, useAuthState } from '../app/auth'
import { useLanguage } from '../components/LanguageToggle'
import { Button } from '../components/ui/Button'
import { Field } from '../components/ui/Field'
import { ErrorBox, Loading } from '../components/ui/Status'
import { useToast } from '../components/ui/Toast'
import { ApiError } from '../lib/api'
import { clerkError, type FormError } from '../lib/clerkErrors'

interface Me {
  role: 'public' | 'officer' | 'viewer' | 'admin'
  state: { code: string; name: string | null } | null
  district: { id: string; name: string | null } | null
  agency: { id: string; name: string | null } | null
  reports: number
  last_admin: boolean
}

/** One settings block: a heading and short explanation on the left, the controls on the right. */
function Section({ title, body, children, danger }: { title: string; body?: string; children: ReactNode; danger?: boolean }) {
  return (
    <section className={`grid gap-4 border-b border-hairline py-8 md:grid-cols-[16rem_minmax(0,1fr)] md:gap-10 ${danger ? 'border-l-4 border-l-overdue pl-4 md:pl-6' : ''}`}>
      <div>
        <h2 className="text-lg font-semibold">{title}</h2>
        {body && <p className="mt-1 text-sm text-road">{body}</p>}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  )
}

function Alert({ error }: { error: FormError | null }) {
  if (!error) return null
  return <p role="alert" className="mt-3 border-l-4 border-overdue pl-3 text-sm">{error.message}</p>
}

function Account({ me }: { me: Me }) {
  const { t } = useTranslation()
  const auth = useAuthState()
  const rows: [string, ReactNode][] = [
    [t('settings.email'), auth.email ?? '—'],
    [t('settings.role'), t(`admin.roles.${me.role}`)],
  ]
  if (me.state) rows.push([t('settings.area'), [me.state.name, me.district?.name].filter(Boolean).join(' › ')])
  if (me.agency?.name) rows.push([t('settings.agency'), me.agency.name])
  rows.push([t('settings.reports'), t('settings.reportCount', { count: me.reports })])
  return (
    <Section title={t('settings.account')} body={t('settings.accountBody')}>
      <dl className="divide-y divide-hairline border-y border-hairline bg-kerb">
        {rows.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[8rem_minmax(0,1fr)] gap-3 px-4 py-3 text-sm">
            <dt className="text-road">{k}</dt><dd className="break-words">{v}</dd>
          </div>
        ))}
      </dl>
    </Section>
  )
}

function Language() {
  const { t } = useTranslation()
  const [lang, setLanguage] = useLanguage()
  return (
    <Section title={t('settings.language')} body={t('settings.languageBody')}>
      <fieldset className="flex flex-wrap gap-3">
        <legend className="sr-only">{t('settings.language')}</legend>
        {(['en', 'ms'] as const).map((l) => (
          <label key={l} lang={l}
            className={`flex min-h-11 cursor-pointer items-center gap-2 rounded border px-4 ${lang === l ? 'border-asphalt bg-kerb font-semibold' : 'border-hairline'}`}>
            <input type="radio" name="lang" value={l} checked={lang === l} onChange={() => setLanguage(l)} className="accent-asphalt" />
            {l === 'en' ? 'English' : 'Bahasa Melayu'}
          </label>
        ))}
      </fieldset>
    </Section>
  )
}

function Password() {
  const { t } = useTranslation()
  const { user } = useUser()
  const toast = useToast()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [error, setError] = useState<FormError | null>(null)
  const [busy, setBusy] = useState(false)
  const update = useReverification((params: { currentPassword: string; newPassword: string }) =>
    user!.updatePassword({ ...params, signOutOfOtherSessions: true }))
  if (!user) return null
  const google = user.externalAccounts.some((a) => a.provider === 'google')

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await update({ currentPassword: current, newPassword: next })
      setCurrent('')
      setNext('')
      toast(t('settings.passwordChanged'))
    } catch (err) {
      setError(clerkError(err, t))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Section title={t('settings.password')} body={t('settings.passwordBody')}>
      {!user.passwordEnabled && google ? (
        <p className="max-w-prose">{t('settings.passwordGoogle')}</p>
      ) : (
        <form onSubmit={submit} className="max-w-sm space-y-4">
          <Field label={t('settings.currentPassword')} type="password" autoComplete="current-password" required
            value={current} onChange={(e) => setCurrent(e.target.value)} />
          <Field label={t('auth.newPassword')} type="password" autoComplete="new-password" required minLength={8}
            hint={t('auth.passwordHint')} value={next} onChange={(e) => setNext(e.target.value)} />
          <Button type="submit" variant="secondary" disabled={busy || !current || next.length < 8}>
            {busy ? t('settings.changingPassword') : t('settings.changePassword')}
          </Button>
          <Alert error={error} />
        </form>
      )}
    </Section>
  )
}

function Google() {
  const { t } = useTranslation()
  const { user } = useUser()
  const toast = useToast()
  const [error, setError] = useState<FormError | null>(null)
  const [busy, setBusy] = useState(false)
  const link = useReverification(() =>
    user!.createExternalAccount({ strategy: 'oauth_google', redirectUrl: `${window.location.origin}/settings` }))
  const google = user?.externalAccounts.find((a) => a.provider === 'google')
  const unlink = useReverification(() => google!.destroy())
  if (!user) return null
  const onlyWay = Boolean(google) && !user.passwordEnabled

  async function run(action: () => Promise<void>) {
    setError(null)
    setBusy(true)
    try {
      await action()
    } catch (err) {
      setError(clerkError(err, t))
      setBusy(false)
    }
  }

  return (
    <Section title={t('settings.google')} body={t('settings.googleBody')}>
      {google ? (
        <div className="space-y-3">
          <p>{t('settings.googleLinked', { email: google.emailAddress })}</p>
          <Button variant="secondary" disabled={busy || onlyWay}
            onClick={() => run(async () => { await unlink(); await user.reload(); toast(t('settings.googleUnlinked')); setBusy(false) })}>
            {t('settings.unlinkGoogle')}
          </Button>
          {onlyWay && <p className="text-sm text-road">{t('settings.googleOnlyWay')}</p>}
        </div>
      ) : (
        <div className="space-y-3">
          <p>{t('settings.googleNotLinked')}</p>
          <Button variant="secondary" disabled={busy}
            onClick={() => run(async () => {
              const account = await link()
              const url = account?.verification?.externalVerificationRedirectURL
              if (url) window.location.href = url.href // Google, then back to /settings
            })}>
            {t('settings.linkGoogle')}
          </Button>
        </div>
      )}
      <Alert error={error} />
    </Section>
  )
}

const CONFIRM_WORD = 'DELETE'

function DeleteAccount({ me }: { me: Me }) {
  const { t } = useTranslation()
  const api = useApi()
  const auth = useAuthState()
  const [typed, setTyped] = useState('')
  const remove = useMutation({
    mutationFn: () => api('/me', { method: 'DELETE' }),
    onSuccess: () => auth.signOut('/welcome?deleted=1'),
  })
  const lastAdmin = me.last_admin || (remove.error instanceof ApiError && remove.error.code === 'LAST_ADMIN')

  return (
    <Section title={t('settings.delete')} body={t('settings.deleteBody')} danger>
      <ul className="max-w-prose list-disc space-y-1 pl-5 text-sm">
        <li>{t('settings.deleteWhat1')}</li>
        <li>{t('settings.deleteWhat2')}</li>
        <li>{t('settings.deleteWhat3')}</li>
      </ul>
      {lastAdmin ? (
        <p role="alert" className="mt-4 max-w-prose font-medium">{t('settings.lastAdmin')}</p>
      ) : (
        <form className="mt-5 max-w-sm space-y-4" onSubmit={(e) => { e.preventDefault(); remove.mutate() }}>
          <Field label={t('settings.typeToConfirm', { word: CONFIRM_WORD })} value={typed} autoComplete="off"
            onChange={(e) => setTyped(e.target.value)} />
          <button type="submit" disabled={typed.trim() !== CONFIRM_WORD || remove.isPending}
            className="inline-flex min-h-11 items-center justify-center rounded border border-overdue bg-kerb px-4 font-semibold text-overdue hover:bg-overdue hover:text-kerb disabled:cursor-not-allowed disabled:opacity-50">
            {remove.isPending ? t('settings.deleting') : t('settings.deleteButton')}
          </button>
          {remove.isError && !lastAdmin && <ErrorBox error={remove.error} />}
        </form>
      )}
    </Section>
  )
}

/** Settings (plan A3): account details, password, language, Google, and deleting the account. */
export default function Settings() {
  const { t } = useTranslation()
  const api = useApi()
  const me = useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/me') })
  return (
    <div className="max-w-5xl px-4 py-8 sm:px-8">
      <h1 className="text-2xl font-semibold">{t('nav.settings')}</h1>
      {me.isPending && <div className="mt-6"><Loading /></div>}
      {me.isError && <div className="mt-6"><ErrorBox error={me.error} onRetry={() => me.refetch()} /></div>}
      {me.data && <Account me={me.data} />}
      <Language />
      {AUTH_CONFIGURED ? (
        <>
          <Password />
          <Google />
        </>
      ) : (
        <Section title={t('settings.password')}><p className="max-w-prose text-road">{t('settings.notConnected')}</p></Section>
      )}
      {me.data && AUTH_CONFIGURED && <DeleteAccount me={me.data} />}
    </div>
  )
}
