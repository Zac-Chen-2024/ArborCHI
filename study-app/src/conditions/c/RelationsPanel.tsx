/**
 * "Who this evidence is about" (C-07).
 *
 * Restraint red line, load-bearing: this panel states facts taken from the
 * documents and makes no assessment. No warning state, no "this contradicts…",
 * no strength colouring, no confidence badge -- and no code path that could
 * render one, because `relations.json` carries subject / predicate / object and
 * nothing else. The schema has nowhere to put a judgement, which is a stronger
 * guarantee than remembering not to show one.
 *
 * Each fact is set as a line of text rather than a row of pills. The pills put
 * three different visual treatments in one 300px row -- a filled black subject,
 * a mono predicate, a bordered object -- and truncated the object, which is the
 * half that carries the content. Weight and colour separate the parts just as
 * well, they wrap instead of clipping, and a fact that reads as a sentence is
 * harder to mistake for a verdict than one boxed like a status chip.
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
  // Optional chaining on the containers, not just the lookups. A bundle that
  // omits `other_mentions` made `undefined[focus_entity]` throw, and with no
  // error boundary above it the whole workspace white-screened the moment a
  // participant selected their first piece of evidence.
  const triples = relations?.relations?.[snippet.snippet_id] ?? []
  const mentions = relations?.other_mentions?.[relations?.focus_entity] ?? []

  // Consecutive facts about the same thing share one heading. Three excerpts
  // from one exhibit routinely describe one entity, and repeating its name
  // above each line read as three separate findings rather than three
  // properties of the same one.
  const groups: { subject: string; facts: { predicate: string; object: string }[] }[] = []
  for (const triple of triples) {
    const last = groups[groups.length - 1]
    if (last && last.subject === triple.subject) {
      last.facts.push({ predicate: triple.predicate, object: triple.object })
    } else {
      groups.push({
        subject: triple.subject,
        facts: [{ predicate: triple.predicate, object: triple.object }],
      })
    }
  }

  return (
    <div className="border-t border-slate-200 bg-white">
      <div
        className="flex items-center gap-2 px-4 border-b border-slate-100"
        style={{ height: 'var(--h-phead)' }}
      >
        <span className="text-[13px] font-bold text-slate-700 truncate">
          {t('relations.title')}
        </span>
        <span className="mono text-[10.5px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 font-semibold flex-shrink-0 ml-auto">
          {t('ref.exPage', { ex: snippet.exhibit, i: snippet.page })}
        </span>
      </div>

      <div className="px-4 py-3" style={{ maxHeight: 150, overflow: 'auto' }}>
        {groups.length === 0 ? (
          <p className="text-[12px] text-slate-400">{t('relations.none')}</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {groups.map((group, i) => (
              <li key={i} className="leading-snug">
                <p className="text-[12.5px] font-semibold text-slate-800 mb-0.5">
                  {group.subject}
                </p>
                {group.facts.map((f, j) => (
                  <p key={j} className="text-[12.5px] text-slate-600">
                    <span className="mono text-[10px] uppercase tracking-wide text-slate-400 mr-1.5">
                      {f.predicate}
                    </span>
                    {f.object}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        )}
        <p className="text-[10px] text-slate-400 mt-3">{t('relations.src')}</p>
      </div>

      {mentions.length > 0 && (
        <div className="px-4 pb-3 pt-2.5 border-t border-slate-100">
          <p className="mono text-[9.5px] uppercase tracking-[0.12em] text-slate-400 mb-2">
            {t('relations.mentions', { name: relations.focus_entity })}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {mentions.map((m) => (
              <button
                key={`${m.exhibit}-${m.page}`}
                onClick={() => onMentionClick(m.exhibit, m.page)}
                className="mono text-[10.5px] px-2 py-1 rounded-md border border-slate-200 text-slate-500 hover:border-blue-300 hover:text-blue-600 hover:bg-blue-50/60 transition-colors"
              >
                {t('ref.exPage', { ex: m.exhibit, i: m.page })}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
