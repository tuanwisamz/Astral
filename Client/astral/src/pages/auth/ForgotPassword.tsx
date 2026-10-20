import { useSignIn } from '@clerk/clerk-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'

import { AUTH_CONFIGURED } from '../../app/auth'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { useToast } from '../../components/ui/Toast'
import { clerkError, type FormError } from '../../lib/clerkErrors'
import { AuthHeading, AuthNotConnected, fieldError, FormAlert } from './shared'

// FR-ACC-03: email → reset code → code + new password → signed in.
function ForgotPasswordForm() {
  const { t } = useTranslation()
  const { isLoaded, signIn, setActive } = useSignIn()
  const navigate = useNavigate()
  const toast = useToast()
  const [step, setStep] = useState<'email' | 'reset'>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
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

  const sendCode = (e?: FormEvent) => {
    e?.preventDefault()
    if (!isLoaded) return
    void run(async () => {
      await signIn.create({ strategy: 'reset_password_email_code', identifier: email })
      if (step === 'reset') toast(t('auth.codeSent'))
      setStep('reset')
    })
  }

  const reset = (e: FormEvent) => {
    e.preventDefault()
    if (!isLoaded) return
    void run(async () => {
      const result = await signIn.attemptFirstFactor({ strategy: 'reset_password_email_code', code, password })
      if (result.status !== 'complete') {
        setError({ field: 'form', message: t('auth.errors.extraStep') })
        return
      }
      await setActive({ session: result.createdSessionId })
      toast(t('auth.passwordUpdated'))
      navigate('/', { replace: true })
    })
  }

  const backToSignIn = (
    <p className="mt-8 text-sm text-road">
      <Link to="/sign-in" className="font-medium text-asphalt underline underline-offset-4">{t('auth.backToSignIn')}</Link>
    </p>
  )

  if (step === 'reset') {
    return (
      <>
        <AuthHeading title={t('auth.newPasswordTitle')} body={t('auth.newPasswordBody', { email })} />
        <FormAlert error={error} />
        <form onSubmit={reset} className="space-y-5" noValidate>
          <Field label={t('auth.code')} inputMode="numeric" autoComplete="one-time-code" maxLength={6} required
            value={code} onChange={(e) => setCode(e.target.value.trim())} error={fieldError(error, 'code')} />
          <Field label={t('auth.newPassword')} type="password" autoComplete="new-password" required value={password}
            onChange={(e) => setPassword(e.target.value)} hint={t('auth.passwordHint')}
            error={fieldError(error, 'password')} />
          <Button type="submit" variant="primary" className="w-full" disabled={pending || code.length < 6 || !password}>
            {t('auth.setNewPassword')}
          </Button>
        </form>
        <Button variant="quiet" className="mt-4 px-0" onClick={() => sendCode()} disabled={pending}>
          {t('auth.resendCode')}
        </Button>
        {backToSignIn}
      </>
    )
  }

  return (
    <>
      <AuthHeading title={t('auth.forgotTitle')} body={t('auth.forgotBody')} />
      <FormAlert error={error} />
      <form onSubmit={sendCode} className="space-y-5" noValidate>
        <Field label={t('auth.email')} type="email" autoComplete="email" required value={email}
          onChange={(e) => setEmail(e.target.value)} error={fieldError(error, 'email')} />
        <Button type="submit" variant="primary" className="w-full" disabled={!isLoaded || pending || !email}>
          {t('auth.sendResetCode')}
        </Button>
      </form>
      {backToSignIn}
    </>
  )
}

export default function ForgotPassword() {
  return AUTH_CONFIGURED ? <ForgotPasswordForm /> : <AuthNotConnected />
}
