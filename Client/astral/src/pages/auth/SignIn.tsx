import { useSignIn } from '@clerk/clerk-react'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { AUTH_CONFIGURED } from '../../app/auth'
import { safeRedirect } from '../../app/guards'
import { Button } from '../../components/ui/Button'
import { Field } from '../../components/ui/Field'
import { clerkError, type FormError } from '../../lib/clerkErrors'
import { AuthHeading, AuthNotConnected, fieldError, FormAlert, GoogleButton, OrDivider } from './shared'

function SignInForm() {
  const { t } = useTranslation()
  const { isLoaded, signIn, setActive } = useSignIn()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const target = safeRedirect(params.get('redirect')) ?? '/'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<FormError | null>(null)
  const [pending, setPending] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!isLoaded) return
    setPending(true)
    setError(null)
    try {
      const result = await signIn.create({ identifier: email, password })
      if (result.status === 'complete') {
        await setActive({ session: result.createdSessionId })
        navigate(target, { replace: true })
      } else {
        setError({ field: 'form', message: t('auth.errors.extraStep') })
      }
    } catch (err) {
      setError(clerkError(err, t))
    } finally {
      setPending(false)
    }
  }

  function google() {
    if (!isLoaded) return
    void signIn
      .authenticateWithRedirect({ strategy: 'oauth_google', redirectUrl: '/sso-callback', redirectUrlComplete: target })
      .catch((err) => setError(clerkError(err, t)))
  }

  return (
    <>
      <AuthHeading title={t('auth.signInTitle')} />
      <FormAlert error={error} />
      <GoogleButton onClick={google} disabled={!isLoaded} />
      <OrDivider />
      <form onSubmit={submit} className="space-y-5" noValidate>
        <Field label={t('auth.email')} type="email" autoComplete="email" required value={email}
          onChange={(e) => setEmail(e.target.value)} error={fieldError(error, 'email')} />
        <Field label={t('auth.password')} type="password" autoComplete="current-password" required value={password}
          onChange={(e) => setPassword(e.target.value)} error={fieldError(error, 'password')} />
        <Link to="/forgot-password" className="inline-block text-sm font-medium underline underline-offset-4">
          {t('auth.forgotLink')}
        </Link>
        <Button type="submit" variant="primary" className="w-full" disabled={!isLoaded || pending}>
          {pending ? t('auth.signingIn') : t('auth.signIn')}
        </Button>
      </form>
      <p className="mt-8 text-sm text-road">
        {t('auth.newHere')}{' '}
        <Link to="/register" className="font-medium text-asphalt underline underline-offset-4">{t('auth.createAccount')}</Link>
      </p>
    </>
  )
}

export default function SignIn() {
  return AUTH_CONFIGURED ? <SignInForm /> : <AuthNotConnected />
}
