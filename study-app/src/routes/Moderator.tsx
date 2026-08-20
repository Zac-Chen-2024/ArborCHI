/**
 * /mod -- moderator panel (MOD-01..07).
 *
 * Deliberately plain. It is not shown to participants, so it gets no design
 * budget; it gets correctness instead. Two entry points (MOD-07):
 *
 *   Test        one click -> mints a test-track session and opens the join link
 *   Experiment  a form -> condition, language and participant code, all required
 *
 * The participant never sees this choice; by the time they open their link the
 * track and condition are already fixed in their token.
 */
import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { LANG_ENDONYM, LANGS } from '../i18n'
import { api, getToken, setToken, type Condition, type CreatedSession, type MonitorRow } from '../lib/api'

interface SessionRow {
  session_id: string
  condition: Condition
  participant_code: string
  lang: string
  track: string
  created_at: string
}

export function Moderator() {
  const { t } = useTranslation()
  const [tokenInput, setTokenInput] = useState(getToken() ?? '')
  const [rows, setRows] = useState<SessionRow[]>([])
  const [monitor, setMonitor] = useState<MonitorRow | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [created, setCreated] = useState<CreatedSession | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [note, setNote] = useState('')

  const [condition, setCondition] = useState<Condition>('c')
  const [lang, setLang] = useState('en')
  const [code, setCode] = useState('')

  const loadSessions = useCallback(async () => {
    try {
      const out = await api.get<{ sessions: SessionRow[] }>('/sessions')
      setRows(out.sessions)
      setError(null)
    } catch {
      setError(t('mod.unauthorized'))
    }
  }, [t])

  useEffect(() => {
    if (getToken()) void loadSessions()
  }, [loadSessions])

  // Live monitoring for the selected session (MOD-04).
  useEffect(() => {
    if (!selected) return
    const tick = async () => {
      try {
        setMonitor(await api.get<MonitorRow>(`/monitor/${selected}`))
      } catch {
        /* transient: keep the previous reading rather than blanking the panel */
      }
    }
    void tick()
    const id = window.setInterval(() => void tick(), 2000)
    return () => window.clearInterval(id)
  }, [selected])

  const create = async (track: 'formal' | 'test') => {
    try {
      const out = await api.post<CreatedSession>('/sessions', {
        condition,
        // A test run still needs a participant code (it is a full dress
        // rehearsal), but nobody should have to invent one.
        participant_code: track === 'test' ? 'TEST' : code,
        lang,
        track,
      })
      setCreated(out)
      setSelected(out.session_id)
      await loadSessions()
      if (track === 'test') window.open(out.join_url, '_blank', 'noopener')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'error')
    }
  }

  const advance = async () => {
    if (!selected) return
    await api.post('/advance', { session_id: selected })
  }

  const saveNote = async () => {
    if (!selected || !note.trim()) return
    await api.post('/note', { session_id: selected, text: note })
    setNote('')
  }

  const heartbeatColour = (ageMs: number | null) => {
    if (ageMs === null) return 'bg-slate-300'
    if (ageMs < 10_000) return 'bg-emerald-500'
    if (ageMs < 30_000) return 'bg-amber-500'
    return 'bg-rose-500'
  }

  return (
    <div className="min-h-full bg-slate-100 p-8 overflow-auto">
      <div className="max-w-[1100px] mx-auto space-y-5">
        <h1 className="text-[20px] font-bold">{t('mod.title')}</h1>

        <section className="bg-white rounded-xl border border-slate-200 p-5">
          <label className="block text-[12px] font-semibold text-slate-500 mb-1.5">{t('mod.token')}</label>
          <div className="flex gap-2">
            <input
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              className="flex-1 px-3 py-2 rounded-lg border border-slate-300 text-[13px] mono"
            />
            <button
              onClick={() => {
                setToken(tokenInput)
                void loadSessions()
              }}
              className="px-4 py-2 rounded-lg bg-slate-900 text-white text-[13px] font-semibold"
            >
              OK
            </button>
          </div>
          {error && <p className="text-[12px] text-rose-600 mt-2">{error}</p>}
        </section>

        <section className="grid grid-cols-2 gap-5">
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <p className="text-[14px] font-bold mb-1">{t('mod.test')}</p>
            <p className="text-[12px] text-slate-500 mb-3">{t('mod.testHint')}</p>
            <button
              onClick={() => void create('test')}
              className="px-4 py-2 rounded-lg border border-slate-300 text-[13px] font-semibold hover:bg-slate-50"
            >
              {t('mod.test')}
            </button>
          </div>

          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <p className="text-[14px] font-bold mb-1">{t('mod.experiment')}</p>
            <p className="text-[12px] text-slate-500 mb-3">{t('mod.experimentHint')}</p>
            <div className="flex gap-2 mb-2">
              <select
                value={condition}
                onChange={(e) => setCondition(e.target.value as Condition)}
                className="px-2.5 py-2 rounded-lg border border-slate-300 text-[13px]"
              >
                <option value="c">{t('mod.conditionC')}</option>
                <option value="b">{t('mod.conditionB')}</option>
              </select>
              <select
                value={lang}
                onChange={(e) => setLang(e.target.value)}
                className="px-2.5 py-2 rounded-lg border border-slate-300 text-[13px]"
              >
                {/* Endonyms: a language picker names each language in its
                    own language, so these deliberately do NOT go through
                    i18n -- translating them would be the bug. */}
                {LANGS.map((l) => (
                  <option key={l} value={l}>
                    {LANG_ENDONYM[l]}
                  </option>
                ))}
              </select>
              <input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder={t('mod.participantCode')}
                className="flex-1 px-3 py-2 rounded-lg border border-slate-300 text-[13px]"
              />
            </div>
            <button
              onClick={() => void create('formal')}
              disabled={!code.trim()}
              className="px-4 py-2 rounded-lg bg-slate-900 text-white text-[13px] font-semibold disabled:opacity-40"
            >
              {t('mod.create')}
            </button>
          </div>
        </section>

        {created && (
          <section className="bg-white rounded-xl border border-slate-200 p-5">
            <p className="text-[12px] font-semibold text-slate-500 mb-1.5">{t('mod.joinLink')}</p>
            <div className="flex gap-2">
              <input readOnly value={created.join_url} className="flex-1 px-3 py-2 rounded-lg border border-slate-300 text-[12px] mono" />
              <button
                onClick={() => void navigator.clipboard.writeText(created.join_url)}
                className="px-4 py-2 rounded-lg border border-slate-300 text-[13px]"
              >
                {t('mod.copy')}
              </button>
            </div>
          </section>
        )}

        <section className="bg-white rounded-xl border border-slate-200 p-5">
          <p className="text-[14px] font-bold mb-3">{t('mod.sessions')}</p>
          {rows.length === 0 && <p className="text-[12.5px] text-slate-400">{t('mod.noSessions')}</p>}
          <div className="space-y-1.5">
            {rows.map((r) => (
              <button
                key={r.session_id}
                onClick={() => setSelected(r.session_id)}
                className={`w-full text-left px-3 py-2 rounded-lg border text-[12.5px] flex items-center gap-3 ${
                  selected === r.session_id ? 'border-slate-900 bg-slate-50' : 'border-slate-200 hover:bg-slate-50'
                }`}
              >
                <span className="mono text-slate-400">{r.session_id.slice(0, 9)}</span>
                <span className="font-semibold">{r.participant_code}</span>
                <span className="uppercase">{r.condition}</span>
                <span className="text-slate-400">{r.lang}</span>
                {r.track === 'test' && (
                  <span className="mono text-[10px] px-1.5 rounded bg-slate-100 text-slate-400 font-bold">TEST</span>
                )}
                <span className="ml-auto text-slate-400">{r.created_at.slice(0, 19).replace('T', ' ')}</span>
              </button>
            ))}
          </div>
        </section>

        {monitor && (
          <section className="bg-white rounded-xl border border-slate-200 p-5 space-y-3">
            <div className="flex items-center gap-4 text-[13px]">
              <span>
                <span className="text-slate-400">{t('mod.phase')}: </span>
                <span className="font-semibold">{monitor.phase}</span>
              </span>
              <span>
                <span className="text-slate-400">{t('mod.next')}: </span>
                {monitor.next_phase ?? '—'}
              </span>
              <span className="flex items-center gap-1.5">
                <span className={`w-2 h-2 rounded-full ${heartbeatColour(monitor.heartbeat_age_ms)}`} />
                <span className="text-slate-400">{t('mod.heartbeat')}: </span>
                <span className="mono">
                  {monitor.heartbeat_age_ms === null ? '—' : `${Math.round(monitor.heartbeat_age_ms / 1000)}s`}
                </span>
              </span>
              {/* Moderator-only clock (MOD-03). The participant build has no
                  component that could render this value. */}
              <span>
                <span className="text-slate-400">{t('mod.remaining')}: </span>
                <span className="mono">
                  {monitor.phase_remaining_ms === null
                    ? '—'
                    : `${Math.max(0, Math.round(monitor.phase_remaining_ms / 1000))}s`}
                </span>
              </span>
              <span className="ml-auto mono text-slate-400">{t('mod.seqLabel', { n: monitor.seq_acked })}</span>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => void advance()}
                disabled={!monitor.next_phase}
                className="px-4 py-2 rounded-lg bg-slate-900 text-white text-[13px] font-semibold disabled:opacity-40"
              >
                {t('mod.advance')} → {monitor.next_phase ?? '—'}
              </button>
            </div>

            <div className="flex gap-2">
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t('mod.note')}
                className="flex-1 px-3 py-2 rounded-lg border border-slate-300 text-[13px]"
              />
              <button onClick={() => void saveNote()} className="px-4 py-2 rounded-lg border border-slate-300 text-[13px]">
                {t('mod.noteSave')}
              </button>
            </div>
          </section>
        )}
      </div>
    </div>
  )
}
