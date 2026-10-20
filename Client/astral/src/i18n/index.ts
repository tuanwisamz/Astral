import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './en.json'
import ms from './ms.json'

// Bahasa Melayu (T8.5) covers every key; English is the fallback if one is ever missed.
function savedLanguage(): string {
  try {
    return localStorage.getItem('lang') ?? 'en'
  } catch {
    return 'en'
  }
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, ms: { translation: ms } },
  lng: savedLanguage(),
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

export default i18n
