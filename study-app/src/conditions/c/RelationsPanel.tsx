/**
 * "Who this evidence is about" (C-07).
 *
 * Restraint red line: this panel states facts extracted from the documents and
 * makes no assessment. There is no warning state, no "this contradicts…", no
 * strength colouring, no confidence badge -- and no code path that could
 * render one. relations.json carries triples only; if an evaluative field ever
 * appears in it, that is a bundle bug, not a rendering opportunity.
 */
import { useTranslation } from 'react-i18next'

import { FOCUS_ENTITY, OTHER_MENTIONS, type Snippet } from '../../data/fixtures'

interface Props {
  snippet: Snippet
  onMentionClick: (ref: string) => void
}

export function RelationsPanel({ snippet, onMentionClick }: Props) {
  const { t } = useTranslation()

  return (
    <div className="border-t border-slate-200 bg-white">
      <div className="flex items-center gap-2 px-4 border-b border-slate-100" style={{ height: 'var(--h-phead)' }}>
        <span className="text-[13px] font-bold text-slate-700">{t('relations.title')}</span>
        <span className="ml-auto text-[10.5px] text-slate-400">{t('relations.src')}</span>
      </div>

      <div className="px-4 py-3 space-y-1.5" style={{ maxHeight: 168, overflow: 'auto' }}>
        {snippet.rel.map(([s, p, o], i) => (
          <div key={i} className="flex items-center gap-2 min-w-0">
            <span className="px-2 py-1 rounded-md bg-slate-900 text-white text-[11.5px] font-medium whitespace-nowrap">
              {s}
            </span>
            <span className="mono text-[10.5px] text-slate-400 whitespace-nowrap">{p}</span>
            <span className="px-2 py-1 rounded-md bg-white border border-slate-300 text-[11.5px] text-slate-700 truncate">
              {o}
            </span>
          </div>
        ))}
        <div className="pt-1.5">
          <span className="mono text-[10.5px] px-1.5 py-0.5 rounded bg-blue-50 border border-blue-200 text-blue-600 font-semibold">
            {t('ref.exPage', { ex: snippet.ex, i: snippet.page })}
          </span>
        </div>
      </div>

      <div className="px-4 pb-3 pt-2 border-t border-slate-100">
        <p className="text-[10.5px] font-bold text-slate-400 tracking-widest mb-1.5">
          {t('relations.mentions', { name: FOCUS_ENTITY })}
        </p>
        <div className="flex flex-wrap gap-1.5">
          {OTHER_MENTIONS.map((ref) => (
            <button
              key={ref}
              onClick={() => onMentionClick(ref)}
              className="mono text-[11px] px-2 py-1 rounded bg-slate-50 border border-slate-200 text-slate-600 hover:border-slate-400"
            >
              {ref}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
