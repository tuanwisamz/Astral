import { isClerkAPIResponseError } from '@clerk/clerk-react/errors'
import type { TFunction } from 'i18next'

export type FormField = 'email' | 'password' | 'code' | 'form'
export interface FormError {
  field: FormField
  message: string
}

// Clerk error codes rewritten in the interface's voice: what happened, and what to do.
const CODES: Record<string, [FormField, string]> = {
  form_identifier_not_found: ['email', 'auth.errors.noAccount'],
  form_password_incorrect: ['password', 'auth.errors.wrongPassword'],
  form_identifier_exists: ['email', 'auth.errors.emailTaken'],
  form_password_pwned: ['password', 'auth.errors.pwned'],
  form_password_length_too_short: ['password', 'auth.errors.tooShort'],
  form_password_not_strong_enough: ['password', 'auth.errors.weak'],
  form_password_validation_failed: ['password', 'auth.errors.weak'],
  form_code_incorrect: ['code', 'auth.errors.wrongCode'],
  verification_expired: ['code', 'auth.errors.codeExpired'],
  verification_failed: ['code', 'auth.errors.wrongCode'],
  strategy_for_user_invalid: ['form', 'auth.errors.googleOnly'],
  too_many_requests: ['form', 'auth.errors.tooMany'],
  user_locked: ['form', 'auth.errors.locked'],
  session_exists: ['form', 'auth.errors.signedIn'],
}

const PARAM_FIELD: Record<string, FormField> = {
  identifier: 'email',
  email_address: 'email',
  password: 'password',
  code: 'code',
}

export function clerkError(err: unknown, t: TFunction): FormError {
  if (!isClerkAPIResponseError(err)) {
    return { field: 'form', message: t('app.offline') }
  }
  const first = err.errors[0]
  const known = first && CODES[first.code]
  if (known) return { field: known[0], message: t(known[1]) }
  if (first?.code === 'form_param_format_invalid' && first.meta?.paramName === 'email_address') {
    return { field: 'email', message: t('auth.errors.invalidEmail') }
  }
  const field = (first?.meta?.paramName && PARAM_FIELD[first.meta.paramName]) || 'form'
  return { field, message: first?.longMessage ?? first?.message ?? t('auth.errors.generic') }
}
