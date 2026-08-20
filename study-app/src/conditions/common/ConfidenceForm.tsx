/**
 * The two confidence questions (FS-08, BE-12).
 *
 * Asked BEFORE the probe, and the server enforces that order (红线 #6). The
 * reason is worth stating where someone might be tempted to reorder the UI for
 * flow: walking a participant through their own sentences one at a time and
 * asking "does this hold up?" changes what they believe about their draft. Ask
 * afterwards and the number measures the probe, not the interface.
 *
 * Both questions are required. A blank Likert is not a neutral answer, it is a
 * missing data point, and there is no way to tell the two apart later.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../../lib/api'
import { logger } from '../../lib/logger'

interface Props {
  onDone: () => void
}

const SCALE = [1, 2, 3, 4, 5, 6, 7]

export function ConfidenceForm({ onDone }: Props) {
  const { t } = useTranslation()
  const [likert, setLikert] = useState<number | null>(null)
  const [count, setCount] = useState('')
  const [busy, setBusy] = useState(false)

  const ready = likert !== null && count.trim() !== '' && Number(count) >= 0

  const submit = async () => {
    if (!ready || busy) return
    setBusy(true)
    logger.log('confidence_submit', {
      likert_1_7: likert,
      est_problem_count: Number(count),
    })
    await logger.flush()
    try {
      await api.post('/confidence', {
        likert_1_7: likert,
        est_problem_count: Number(count),
      })
      onDone()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-full grid place-items-center bg-slate-100">
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 px-10 py-9 w-[620px]">
        <p className="text-[15px] font-semibold mb-6">{t('conf.likert')}</p>
        <div className="flex items-center gap-2 mb-2">
          {SCALE.map((n) => (
            <button
              key={n}
              onClick={() => setLikert(n)}
              className={`flex-1 py-3 rounded-lg border text-[14px] font-semibold ${
                likert === n
                  ? 'bg-slate-900 text-white border-slate-900'
                  : 'bg-white text-slate-600 border-slate-200 hover:border-slate-400'
              }`}
            >
              {n}
            </button>
          ))}
        </div>
        <div className="flex justify-between text-[11px] text-slate-400 mb-8">
          <span>{t('conf.scaleLow')}</span>
          <span>{t('conf.scaleHigh')}</span>
        </div>

        <p className="text-[15px] font-semibold mb-3">{t('conf.count')}</p>
        <input
          type="number"
          min={0}
          value={count}
          onChange={(e) => setCount(e.target.value)}
          className="w-full px-3 py-2.5 rounded-lg border border-slate-300 text-[14px] mb-8"
        />

        <button
          onClick={() => void submit()}
          disabled={!ready || busy}
          className="w-full py-3 rounded-xl bg-slate-900 text-white text-[14px] font-semibold hover:bg-slate-800 disabled:opacity-40"
        >
          {t('conf.submit')}
        </button>
      </div>
    </div>
  )
}
