import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { buttonClass } from './ui/Button'

/** EN / BM switch (T8.5). The button names the language you switch to, in that language. */
export function LanguageToggle({ className = '' }: { className?: string }) {
  const { t, i18n } = useTranslation()
  const next = i18n.language === 'ms' ? 'en' : 'ms'

  useEffect(() => {
    document.documentElement.lang = i18n.language
  }, [i18n.language])

  function toggle() {
    void i18n.changeLanguage(next)
    try {
      localStorage.setItem('lang', next)
    } catch {
      // Not remembered in private mode; the switch still works for this visit.
    }
  }

  return (
    <button type="button" onClick={toggle} lang={next} className={buttonClass('quiet', `px-2 ${className}`)}
      aria-label={t('common.language')}>
      <span aria-hidden="true">{t('common.languageShort')}</span>
    </button>
  )
}
