/**
 * Sentence-by-sentence probe (FS-09, BE-13).
 *
 * One item at a time, three choices, and the source available on request. The
 * measurements are the judgement, the reaction time, and whether they opened
 * the source before answering -- that last one is why "View source" is a button
 * and not a permanently open panel: if the evidence were always on screen,
 * "did they look?" would have no answer.
 *
 * The reaction-time clock starts when the item is rendered and stops on the
 * answer. It is deliberately not paused when the source is opened: time spent
 * checking IS the behaviour, and subtracting it would remove the thing being
 * measured from the measurement.
 *
 * No progress bar beyond the plain count. A participant who can see the end
 * approaching speeds up, and the last items would be systematically different
 * from the first.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../../lib/api'
import { logger } from '../../lib/logger'
import type { Material } from '../../lib/material'

export interface ProbeItem {
  probe_index: number
  sent_id: string | null
  text: string
  citations: string[]
}

type Judgment = 'supported' | 'not_supported' | 'unsure'

interface Props {
  material: Material
  onDone: () => void
}

/** "[Exhibit C-1, p.2]" -> { exhibit, page } so the source can be shown.
 *
 * The id class allows a hyphen. Without it this matched the placeholder
 * bundle's ids (`B2`, `C1`) and nothing else -- and a real filing numbers its
 * exhibits the way the brief does, `C-1`, `G-5`. Parsing then failed, `source`
 * came back null, and the "View source" button simply did not render: no way to
 * check the evidence during the probe, and `source_opened` false for every item
 * in every session. It is one of the measures the study exists to collect. */
export function parseCitation(cite: string): { exhibit: string; page: number } | null {
  const m = /\[Exhibit\s+([A-Za-z0-9][A-Za-z0-9-]*),\s*p\.\s*(\d+)/.exec(cite)
  return m ? { exhibit: m[1], page: Number(m[2]) } : null
}

export function ProbeRunner({ material, onDone }: Props) {
  const { t } = useTranslation()
  const [items, setItems] = useState<ProbeItem[] | null>(null)
  const [index, setIndex] = useState(0)
  const [sourceOpen, setSourceOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const shownAt = useRef(performance.now())
  const openedSource = useRef(false)

  useEffect(() => {
    void (async () => {
      const out = await api.post<{ items: ProbeItem[]; answered: Record<string, unknown> }>(
        '/probe/start',
      )
      setItems(out.items)
      // A reload mid-probe resumes where it stopped rather than starting over.
      setIndex(Object.keys(out.answered ?? {}).length)
    })()
  }, [])

  const item = items?.[index]

  useEffect(() => {
    shownAt.current = performance.now()
    openedSource.current = false
    setSourceOpen(false)
  }, [index])

  const source = useMemo(() => {
    if (!item?.citations.length) return null
    const ref = parseCitation(item.citations[0])
    if (!ref) return null
    const snippet = Object.values(material.snippets).find(
      (s) => s.exhibit === ref.exhibit && s.page === ref.page,
    )
    return snippet ? { ...ref, snippet } : { ...ref, snippet: null }
  }, [item, material.snippets])

  const answer = async (judgment: Judgment) => {
    if (!item || busy) return
    setBusy(true)
    const rt = Math.round(performance.now() - shownAt.current)
    logger.log('probe_item', {
      probe_index: item.probe_index,
      sent_id: item.sent_id,
      judgment,
      rt_ms: rt,
      source_opened: openedSource.current,
    })
    try {
      await api.post('/probe/answer', {
        probe_index: item.probe_index,
        judgment,
        rt_ms: rt,
        source_opened: openedSource.current,
      })
      if (items && index + 1 >= items.length) {
        await logger.flush()
        onDone()
      } else {
        setIndex((i) => i + 1)
      }
    } finally {
      setBusy(false)
    }
  }

  if (!items) return null
  if (!item) return null

  const choices: { key: Judgment; label: string; tone: string }[] = [
    { key: 'supported', label: t('probe.supported'), tone: 'border-emerald-300 hover:bg-emerald-50' },
    { key: 'not_supported', label: t('probe.notSupported'), tone: 'border-rose-300 hover:bg-rose-50' },
    { key: 'unsure', label: t('probe.unsure'), tone: 'border-slate-300 hover:bg-slate-50' },
  ]

  return (
    <div className="h-full grid place-items-center bg-slate-100 p-8">
      <div className="w-[760px]">
        <p className="mono text-[11.5px] text-slate-400 mb-3">
          {t('probe.progress', { i: index + 1, n: items.length })}
        </p>

        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 px-8 py-7">
          <p className="text-[15px] leading-[1.85] text-slate-800 mb-6">{item.text}</p>

          {source && (
            <div className="mb-6">
              {!sourceOpen ? (
                <button
                  onClick={() => {
                    openedSource.current = true
                    setSourceOpen(true)
                    logger.log('doc_open', {
                      exhibit: source.exhibit, page: source.page, via: 'probe',
                    })
                  }}
                  className="px-3 py-1.5 rounded-lg border border-slate-200 text-[12.5px] text-slate-600 hover:bg-slate-50"
                >
                  {t('probe.viewSource')}
                </button>
              ) : (
                <div className="rounded-lg border border-blue-200 bg-blue-50/60 px-4 py-3">
                  <p className="mono text-[10.5px] text-blue-600 font-semibold mb-1.5">
                    {t('ref.exPage', { ex: source.exhibit, i: source.page })}
                  </p>
                  <p className="text-[13px] leading-relaxed text-slate-800">
                    {source.snippet?.text ?? t('probe.sourceUnavailable')}
                  </p>
                </div>
              )}
            </div>
          )}

          <p className="text-[13.5px] font-semibold text-slate-700 mb-3">{t('probe.q')}</p>
          <div className="flex gap-2">
            {choices.map((c) => (
              <button
                key={c.key}
                disabled={busy}
                onClick={() => void answer(c.key)}
                className={`flex-1 py-3 rounded-xl border bg-white text-[13.5px] font-medium text-slate-700 disabled:opacity-40 ${c.tone}`}
              >
                {c.label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
