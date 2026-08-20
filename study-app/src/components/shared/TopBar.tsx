/**
 * Top bar, 56px, shared by both conditions (FS-01).
 *
 * The phase tag is the only thing that differs between conditions, and the
 * countdown is the only thing that differs between phases: it renders when --
 * and only when -- the server sent a remaining time. There is no `else`
 * branch that shows an elapsed timer or a phase length instead (红线 #4).
 */
import { useTranslation } from 'react-i18next'

import { BUILD_HASH } from '../../lib/session'
import type { Condition, Track } from '../../lib/api'

interface Props {
  condition: Condition
  track: Track
  phaseLabel: string
  /** ms, or null when the participant may not see a clock. */
  remainingMs: number | null
  /** The protocol allows the participant to end this phase themselves.
    *  Drives whether the submit button is live -- and nothing else: it must
    *  not become a proxy for "time is nearly up" (红线 #4). */
  canSubmit: boolean
  onHelp: () => void
  onSubmit: () => void
}

function formatClock(ms: number): string {
  const total = Math.max(0, Math.round(ms / 1000))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function TopBar({ condition, track, phaseLabel, remainingMs, canSubmit, onHelp, onSubmit }: Props) {
  const { t } = useTranslation()

  return (
    <header className="bg-white border-b border-slate-200 flex items-center px-5 gap-4 min-w-0">
      <span className="text-[16px] font-bold tracking-tight flex-shrink-0">
        {condition === 'c' ? t('app.titleC') : t('app.titleB')}
      </span>
      {track === 'test' && (
        // FS-11: visible only on the test track, deliberately grey so that a
        // formal session is not distinguishable by anything at all.
        <span className="mono text-[10px] px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200 text-slate-400 font-bold flex-shrink-0">
          {t('topbar.test')}
        </span>
      )}
      <span className="w-px h-5 bg-slate-200 flex-shrink-0" />
      <span className="text-[13px] text-slate-500 truncate flex-shrink-0">{t('app.case')}</span>
      <span className="w-px h-5 bg-slate-200 flex-shrink-0" />
      <div className="flex items-baseline gap-2 min-w-0">
        <h1 className="text-[15px] font-bold truncate">{t('app.criterion')}</h1>
        <span className="mono text-[11.5px] text-slate-400 flex-shrink-0 hidden xl:inline">
          {t('app.cfr')}
        </span>
      </div>

      <div className="ml-auto flex items-center gap-3 flex-shrink-0">
        {remainingMs !== null && (
          <span className="mono text-[13px] px-2.5 py-1 rounded-full bg-slate-900 text-white font-semibold tabular-nums">
            {formatClock(remainingMs)}
          </span>
        )}
        <span className="text-[11.5px] px-2.5 py-1 rounded-full bg-slate-100 border border-slate-200 text-slate-500 font-medium">
          {phaseLabel}
        </span>
        <span className="mono text-[10px] text-slate-300 hidden 2xl:inline">
          {t('app.build', { hash: BUILD_HASH })}
        </span>
        <button
          onClick={onHelp}
          className="px-3 py-1.5 rounded-lg border border-slate-200 text-[12.5px] text-slate-600 font-medium hover:bg-slate-50"
        >
          {t('topbar.help')}
        </button>
        <button
          onClick={onSubmit}
          disabled={!canSubmit}
          className="px-4 py-2 rounded-lg bg-slate-900 text-white text-[13px] font-semibold hover:bg-slate-800 disabled:opacity-40 disabled:hover:bg-slate-900"
        >
          {condition === 'c' ? t('topbar.submitFinal') : t('topbar.submitDraft')}
        </button>
      </div>
    </header>
  )
}
