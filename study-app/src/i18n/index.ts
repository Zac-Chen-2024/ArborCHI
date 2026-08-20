/**
 * i18n bootstrap (§6, FS-03).
 *
 * Default is English. The language for a run is decided by the moderator when
 * the session is created and arrives on `/state`; the participant has NO
 * switcher -- one session, one language, because mixed-language sessions
 * cannot be pooled in the analysis.
 *
 * Material content (exhibit text, generated letter text) is English and does
 * NOT go through i18n. This file only covers interface chrome.
 */
import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './en.json'
import zh from './zh.json'

export const LANGS = ['en', 'zh'] as const
export type Lang = (typeof LANGS)[number]

/**
 * Each language named in its own language. Endonyms are deliberately NOT
 * translated -- a picker that renders 'Chinese' to an English reader is
 * useless to the person looking for 中文.
 */
export const LANG_ENDONYM: Record<Lang, string> = { en: 'English', zh: '中文' }

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, zh: { translation: zh } },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
  // A missing key must be loud in development -- a silently blank label is
  // worse than an obviously wrong one when the run has already started.
  saveMissing: import.meta.env.DEV,
  missingKeyHandler: import.meta.env.DEV
    ? (_lng, _ns, key) => console.error(`[i18n] missing key: ${key}`)
    : undefined,
})

/** Called once when /state tells us which language this session runs in. */
export function applySessionLang(lang: string): void {
  const next: Lang = (LANGS as readonly string[]).includes(lang) ? (lang as Lang) : 'en'
  if (i18n.language !== next) void i18n.changeLanguage(next)
  document.documentElement.lang = next
}

export default i18n
