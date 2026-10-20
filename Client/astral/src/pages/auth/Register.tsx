import { useSignUp } from '@clerk/clerk-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'

import { AUTH_CONFIGURED } from '../../app/auth'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { useToast } from '../../components/ui/Toast'
import { clerkError, type FormError } from '../../lib/clerkErrors'
import { AuthHeading, AuthNotConnected, fieldError, FormAlert, GoogleButton, OrDivider } from './shared'

// Email and password only: the spec asks for minimal personal data (FR-ACC-02, NFR-03).
// Every new account is public; staff roles come from an admin (spec §3).
function RegisterForm() {
  const { t } = useTranslation()
  const { isLoaded, signUp, setActive } = useSignUp()
  const navigate = useNavigate()
  const toast = useToast()
  const [step, setStep] = useState<'details' | 'verify'>('details')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<FormError | null>(null)
  const [pending, setPending] = useState(false)

  async function run(action: () => Promise<void>) {
    setPending(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(clerkError(err, t))
    } finally {
      setPending(false)
    }
  }

  const createAccount = (e: FormEvent) => {
    e.preventDefault()
    if (!isLoaded) return
    void run(async () => {
      await signUp.create({ emailAddress: email, password })
      await signUp.prepareEmailAddressVerification({ strategy: 'email_code' })
      setStep('verify')
    })
  }

  const verify = (e: FormEvent) => {
    e.preventDefault()
    if (!isLoaded) return
    void run(async () => {
      const result = await signUp.attemptEmailAddressVerification({ code })
      if (result.status !== 'complete') {
        setError({ field: 'form', message: t('auth.errors.extraStep') })
        return
      }
      await setActive({ session: result.createdSessionId })
      toast(t('auth.accountCreated'))
      navigate('/', { replace: true })
    })
  }

  const resend = () =>
    void run(async () => {
      await signUp?.prepareEmailAddressVerification({ strategy: 'email_code' })
      toast(t('auth.codeSent'))
    })

  function google() {
    if (!isLoaded) return
    void signUp
      .authenticateWithRedirect({ strategy: 'oauth_google', redirectUrl: '/sso-callback', redirectUrlComplete: '/' })
      .catch((err) => setError(clerkError(err, t)))
  }

  if (step === 'verify') {
    return (
      <>
        <AuthHeading title={t('auth.verifyTitle')} body={t('auth.verifyBody', { email })} />
        <FormAlert error={error} />
        <form onSubmit={verify} className="space-y-5" noValidate>
          <Field label={t('auth.code')} inputMode="numeric" autoComplete="one-time-code" maxLength={6} required
            value={code} onChange={(e) => setCode(e.target.value.trim())} error={fieldError(error, 'code')} />
          <Button type="submit" variant="primary" className="w-full" disabled={pending || code.length < 6}>
            {t('auth.verifyEmail')}
          </Button>
        </form>
        <Button variant="quiet" className="mt-4 px-0" onClick={resend} disabled={pending}>{t('auth.resendCode')}</Button>
      </>
    )
  }

  return (
    <>
      <AuthHeading title={t('auth.registerTitle')} body={t('auth.registerBody')} />
      <FormAlert error={error} />
      <GoogleButton onClick={google} disabled={!isLoaded} />
      <OrDivider />
      <form onSubmit={createAccount} className="space-y-5" noValidate>
        <Field label={t('auth.email')} type="email" autoComplete="email" required value={email}
          onChange={(e) => setEmail(e.target.value)} error={fieldError(error, 'email')} />
        <Field label={t('auth.password')} type="password" autoComplete="new-password" required value={password}
          onChange={(e) => setPassword(e.target.value)} hint={t('auth.passwordHint')}
          error={fieldError(error, 'password')} />
        {/* Clerk's bot protection renders its challenge here in custom sign-up flows. */}
        <div id="clerk-captcha" />
        <p className="text-sm text-road">{t('auth.privacy')}</p>
        <Button type="submit" variant="primary" className="w-full" disabled={!isLoaded || pending}>
          {pending ? t('auth.creating') : t('auth.createAccount')}
        </Button>
      </form>
      <p className="mt-8 text-sm text-road">
        {t('auth.haveAccount')}{' '}
        <Link to="/sign-in" className="font-medium text-asphalt underline underline-offset-4">{t('auth.signIn')}</Link>
      </p>
    </>
  )
}

export default function Register() {
  return AUTH_CONFIGURED ? <RegisterForm /> : <AuthNotConnected />
}
