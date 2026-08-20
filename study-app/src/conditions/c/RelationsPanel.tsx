/**
 * "Who this evidence is about" (C-07).
 *
 * Restraint red line: this panel states facts extracted from the documents and
 * makes no assessment. There is no warning state, no "this contradicts…", no
 * strength colouring, no confidence badge -- and, more to the point, no code
 * path that could render one, because `relations.json` carries subject /
 * predicate / object and nothing else. The schema has nowhere to put a
 * judgement, which is a stronger guarantee than remembering not to show it.
 */
import { useTranslation } from 'react-i18next'

import type { Relations, Snippet } from '../../lib/material'

interface Props {
  snippet: Snippet
  relations: Relations
  onMentionClick: (exhibit: string, page: number) => void
}

export function RelationsPanel({ snippet, relations, onMentionClick }: Props) {
  const { t } = useTranslation()
  const triples = relations.relations[snippet.snippet_id] ?? []
  const mentions = relations.other_mentions[relations.focus_entity] ?? []

  return (
    <div className="border-t border-slate-200 bg-white">
      <div className="flex items-center gap-2 px-4 border-b border-slate-100" style={{ height: 'var(--h-phead)' }}>
        <span className="text-[13px] font-bold text-slate-700">{t('relations.title')}</span>
        <span className="ml-auto text-[10.5px] text-slate-400">{t('relations.src')}</span>
      </div>

      <div className="px-4 py-3 space-y-1.5" style={{ maxHeight: 168, overflow: 'auto' }}>
        {triples.map((triple, i) => (
          <div key={i} className="flex items-center gap-2 min-w-0">
            <span className="px-2 py-1 rounded-md bg-slate-900 text-white text-[11.5px] font-medium whitespace-nowrap">
              {triple.subject}
            </span>
            <span className="mono text-[10.5px] text-slate-400 whitespace-nowrap">{triple.predicate}</span>
            <span className="px-2 py-1 rounded-md bg-white border border-slate-300 text-[11.5px] text-slate-700 truncate">
              {triple.object}
            </span>
          </div>
        ))}
        <div className="pt-1.5">
          <span className="mono text-[10.5px] px-1.5 py-0.5 rounded bg-blue-50 border border-blue-200 text-blue-600 font-semibold">
            {t('ref.exPage', { ex: snippet.exhibit, i: snippet.page })}
          </span>
        </div>
      </div>

      <div className="px-4 pb-3 pt-2 border-t border-slate-100">
        <p className="text-[10.5px] font-bold text-slate-400 tracking-widest mb-1.5">
          {t('relations.mentions', { name: relations.focus_entity })}
        </p>
        <div className="flex flex-wrap gap-1.5">
          {mentions.map((m) => (
            <button
              key={`${m.exhibit}-${m.page}`}
              onClick={() => onMentionClick(m.exhibit, m.page)}
              className="mono text-[11px] px-2 py-1 rounded bg-slate-50 border border-slate-200 text-slate-600 hover:border-slate-400"
            >
              {t('ref.exPage', { ex: m.exhibit, i: m.page })}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
