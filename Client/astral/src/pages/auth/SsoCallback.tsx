import { AuthenticateWithRedirectCallback } from '@clerk/clerk-react'
import { useTranslation } from 'react-i18next'

import { AUTH_CONFIGURED } from '../../app/auth'
import { AuthNotConnected } from './shared'

/** Finishes the Google redirect. A first-time Google user is moved on to sign-up automatically. */
export default function SsoCallback() {
  const { t } = useTranslation()
  if (!AUTH_CONFIGURED) return <AuthNotConnected />
  return (
    <>
      <p className="text-road">{t('auth.finishingGoogle')}</p>
      <AuthenticateWithRedirectCallback signInUrl="/sign-in" signUpUrl="/register" />
    </>
  )
}
