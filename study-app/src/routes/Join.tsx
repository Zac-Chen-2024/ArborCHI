/**
 * /join?token=… -- the participant's front door (FS-02, FS-12).
 *
 * Stores the token, asks the server who this is, then hands over to the
 * router. Nothing here chooses a condition; `/state` does.
 *
 * The Start page has exactly one button (FS-12). No condition picker, no
 * language picker, no "resume where I left off" -- everything is already
 * decided by the token, so there is nothing for the participant to get wrong.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { applySessionLang } from '../i18n'
import { api, setToken, type StudyState } from '../lib/api'
import { useSession } from '../lib/session'

export function Join() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const refresh = useSession((s) => s.refresh)
  const [status, setStatus] = useState<'checking' | 'ready' | 'error'>('checking')
  const [state, setState] = useState<StudyState | null>(null)
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    const token = params.get('token')
    if (token) setToken(token)
    void (async () => {
      try {
        const next = await api.get<StudyState>('/state')
        // The very first screen must already be in the session's language.
        // Reading /state directly (rather than through the store) would skip
        // this and show a zh participant an English Start page.
        applySessionLang(next.lang)
        setState(next)
        if (next.started) {
          navigate(`/${next.condition}`, { replace: true })
          return
        }
        setStatus('ready')
      } catch {
        setStatus('error')
      }
    })()
  }, [params, navigate])

  const start = async () => {
    setStarting(true)
    try {
      const state = await api.post<StudyState>('/start')
      await refresh()
      navigate(`/${state.condition}`, { replace: true })
    } catch {
      setStatus('error')
      setStarting(false)
    }
  }

  return (
    <div className="h-full grid place-items-center bg-slate-100">
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 px-10 py-9 w-[420px] text-center">
        {/* The product name a participant sees must be their own condition's:
            a DraftDesk participant greeted by "Arbor" is both wrong and a hint
            that another version exists. */}
        <p className="text-[20px] font-bold tracking-tight mb-1">
          {t(state?.condition === 'b' ? 'app.titleB' : 'app.titleC')}
        </p>

        {status === 'checking' && <p className="text-[13px] text-slate-500 mt-4">{t('join.checking')}</p>}

        {status === 'error' && <p className="text-[13px] text-rose-600 mt-4">{t('join.invalid')}</p>}

        {status === 'ready' && (
          <>
            <p className="text-[13px] text-slate-500 mb-7">{t('join.ready')}</p>
            <button
              onClick={() => void start()}
              disabled={starting}
              className="w-full py-3 rounded-xl bg-slate-900 text-white text-[14px] font-semibold hover:bg-slate-800 disabled:opacity-50"
            >
              {t('join.start')}
            </button>
            <p className="text-[11.5px] text-slate-400 mt-3">{t('join.startHint')}</p>
          </>
        )}
      </div>
    </div>
  )
}
