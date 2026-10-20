import { useCallback, useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { useAuthState } from '../app/auth'
import { buttonClass } from './ui/Button'

/** Switches the language here, in this browser, and on the account when signed in. */
export function useLanguage() {
  const { i18n } = useTranslation()
  const auth = useAuthState()
  const setLanguage = useCallback((lang: string) => {
    void i18n.changeLanguage(lang)
    try {
      localStorage.setItem('lang', lang)
    } catch {
      // Not remembered in private mode; the switch still works for this visit.
    }
    if (auth.isSignedIn) void auth.saveLanguage(lang).catch(() => {})
  }, [i18n, auth])
  return [i18n.language === 'ms' ? 'ms' : 'en', setLanguage] as const
}

/** EN / BM switch (T8.5). The button names the language you switch to, in that language. */
export function LanguageToggle({ className = '' }: { className?: string }) {
  const { t, i18n } = useTranslation()
  const [lang, setLanguage] = useLanguage()
  const next = lang === 'ms' ? 'en' : 'ms'

  useEffect(() => {
    document.documentElement.lang = i18n.language
  }, [i18n.language])

  return (
    <button type="button" onClick={() => setLanguage(next)} lang={next} className={buttonClass('quiet', `px-2 ${className}`)}
      aria-label={t('common.language')}>
      <span aria-hidden="true">{t('common.languageShort')}</span>
    </button>
  )
}
