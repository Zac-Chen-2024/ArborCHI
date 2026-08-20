/**
 * Petition letter panel (C-08/C-09/C-10).
 *
 * Citations are rendered as clickable spans, and a click runs the four-step
 * trace-back the study measures: highlight the sub-argument -> highlight its
 * chip -> scroll the bbox into view -> update the breadcrumb. That chain is
 * driven from ConditionC so all four stay in one place and one log event.
 *
 * A paragraph with no generated text renders the mockup's skeleton bars rather
 * than an empty box, so the participant can see the structure the letter will
 * take before generation runs.
 *
 * live vs frozen sentences look IDENTICAL (红线 #3 / C-14): the `source` field
 * rides along in the data for the analysis, and nothing in this component may
 * branch on it.
 */
import { useTranslation } from 'react-i18next'

import { LETTER, SNIPPETS } from '../../data/fixtures'

interface Props {
  focusedSub: string | null
  staleCount: number
  onCiteClick: (snippetId: string) => void
  onRegenerate: () => void
  registerParaRef: (sub: string, el: HTMLDivElement | null) => void
}

export function LetterPanel({
  focusedSub,
  staleCount,
  onCiteClick,
  onRegenerate,
  registerParaRef,
}: Props) {
  const { t } = useTranslation()

  return (
    <aside
      className="panel bg-white border-l border-slate-200"
      style={{ gridTemplateRows: staleCount > 0 ? 'auto auto minmax(0,1fr)' : 'auto minmax(0,1fr)' }}
    >
      <div className="phead" style={{ justifyContent: 'space-between' }}>
        <span className="text-[13.5px] font-bold text-slate-700">
          {t('letter.title', { criterion: t('app.criterion') })}
        </span>
        <button
          onClick={onRegenerate}
          className="text-[12px] text-slate-400 flex items-center gap-1.5 hover:text-slate-600"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24">
            <path d="M16 9h5V4M3 15v5h5M4 9a8 8 0 0113-3l4 3M20 15a8 8 0 01-13 3l-4-3" />
          </svg>
          {t('letter.regenAll')}
        </button>
      </div>

      {staleCount > 0 && (
        <div
          className="flex items-center gap-2 px-4 bg-amber-50 border-b border-amber-200"
          style={{ height: 'var(--h-status)' }}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 flex-shrink-0" />
          <span className="text-[12px] text-amber-800 truncate">{t('letter.stale', { n: staleCount })}</span>
          <button
            onClick={onRegenerate}
            className="ml-auto text-[12px] text-amber-900 font-semibold underline underline-offset-2 flex-shrink-0"
          >
            {t('letter.regen')}
          </button>
        </div>
      )}

      <div className="scroll px-5 py-4">
        {LETTER.map((section) => (
          <div key={section.argId}>
            <h2 className="text-[15px] font-semibold mb-2.5">{section.heading}</h2>
            {section.paras.map((para) => (
              <div
                key={para.sub}
                ref={(el) => registerParaRef(para.sub, el)}
                className={`para mb-2.5${focusedSub === para.sub ? ' is-focus' : ''}`}
                data-sub={para.sub}
              >
                {para.text ? (
                  <p className="text-[13px] leading-[1.8] text-slate-800">
                    {para.text}{' '}
                    {para.citeSnippetId && (
                      <span
                        className="cite"
                        role="button"
                        tabIndex={0}
                        onClick={() => onCiteClick(para.citeSnippetId!)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') onCiteClick(para.citeSnippetId!)
                        }}
                      >
                        {t('letter.cite', {
                          ex: SNIPPETS[para.citeSnippetId].ex,
                          i: SNIPPETS[para.citeSnippetId].page,
                        })}
                      </span>
                    )}
                  </p>
                ) : (
                  para.bars?.map((w, i) => (
                    <div
                      key={i}
                      className="bar"
                      style={{ width: `${w}%`, marginBottom: i === para.bars!.length - 1 ? 0 : undefined }}
                    />
                  ))
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </aside>
  )
}
