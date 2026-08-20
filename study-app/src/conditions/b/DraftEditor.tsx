/**
 * Draft editor (B-02). A plain textarea, on purpose.
 *
 * Citations here are ordinary characters. They are not parsed, not linkified,
 * not hoverable -- clicking one does nothing at all. That inertness is the
 * manipulation: condition C's citations trace back to the source, and B's do
 * not. A rich editor that quietly recognised "[Exhibit B1, p.2]" would put
 * part of C's affordance into the baseline and cost the comparison.
 *
 * The sentence and citation counters are display-only; the analysis recomputes
 * both from the submitted text with the same regex the product's LetterPanel
 * uses, so the two never disagree.
 */
import { useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { logger } from '../../lib/logger'
import { countCitations, countSentences } from '../../lib/sentences'
import { EditReporter } from '../../lib/textEdit'

interface Props {
  value: string
  onChange: (value: string) => void
}

export function DraftEditor({ value, onChange }: Props) {
  const { t } = useTranslation()
  const citations = countCitations(value)

  // One reporter for the lifetime of the editor: it holds the sentence list
  // that lineage is computed against, so recreating it would break the chain
  // (红线 #2).
  const reporter = useMemo(
    () => new EditReporter('draft', (payload) => logger.log('text_edit', payload), value),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )
  // Any pending edit must reach the log before the component goes away --
  // otherwise the last thing the participant typed is the thing that is missing.
  useEffect(() => () => reporter.flushNow(), [reporter])

  return (
    <aside className="panel bg-white border-l border-slate-200" style={{ gridTemplateRows: 'auto minmax(0,1fr) auto' }}>
      <div className="phead" style={{ justifyContent: 'space-between' }}>
        <span className="text-[13.5px] font-bold text-slate-700">{t('draft.title')}</span>
        <span className="text-[11px] text-slate-400">{t('draft.hint')}</span>
      </div>

      <div className="px-5 py-4 overflow-hidden">
        <textarea
          id="editor"
          spellCheck={false}
          value={value}
          onChange={(e) => {
            onChange(e.target.value)
            reporter.onChange(e.target.value)
          }}
          onBlur={() => reporter.flushNow()}
          onFocus={() => logger.log('panel_focus', { panel: 'draft' })}
        />
      </div>

      <div className="flex items-center px-4 border-t border-slate-200" style={{ height: 'var(--h-status)' }}>
        <span className="mono text-[11px] text-slate-400">
          {t('draft.stats', { s: countSentences(value), c: citations })}
        </span>
        <span className="ml-auto text-[11px] text-slate-400">{t('draft.saved')}</span>
      </div>
    </aside>
  )
}
