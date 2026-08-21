/**
 * Petition letter panel (C-08/C-09/C-10).
 *
 * Renders the generated sentences grouped by the node that produced them, so a
 * citation click can trace back: highlight the sub-argument -> highlight its
 * chip -> locate the passage -> update the breadcrumb. That chain is driven
 * from ConditionC so all four move together and produce one log event.
 *
 * ## live and frozen look identical
 *
 * Every sentence carries `source: "frozen" | "live"`, and this component does
 * not read it. Not for styling, not for ordering, not for a tooltip. A
 * participant who could tell which sentences were regenerated would be
 * verifying a different artefact than one who could not, and the comparison
 * would be measuring the cue rather than the behaviour (红线 #3).
 *
 * ## editing
 *
 * The whole letter is one textarea rather than per-sentence inputs. Sentence
 * identity is recovered by alignment (lib/textEdit.ts) rather than by DOM
 * structure, because the participant must be free to merge two sentences or
 * split one -- operations a per-sentence editor makes awkward and which are
 * exactly what the lineage rules exist to track (红线 #2).
 */
import { useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import type { LetterSentence } from '../../lib/material'
import { logger } from '../../lib/logger'
import { EditReporter } from '../../lib/textEdit'

interface Props {
  sentences: LetterSentence[]
  /** From the bundle, so the practice phase does not show the real case's
   *  criterion in the letter heading. */
  criterion: string
  /** Present once the participant starts editing; until then the rendered,
   *  citation-clickable view is shown. */
  editedText: string | null
  focusedSub: string | null
  argumentTitles: Record<string, { index: string; title: string }>
  staleNodeIds: string[]
  generating: boolean
  onCiteClick: (snippetId: string) => void
  onRegenerate: () => void
  onEdit: (text: string) => void
  registerParaRef: (sub: string, el: HTMLDivElement | null) => void
}

/** Splits "text [Exhibit B1, p.2]" into prose and citation runs. */
const CITE_SPLIT = /(\[Exhibit\s+[^\]]+\])/g
/** Separate, NON-global pattern for testing a part. `.test()` on a /g regex
 *  advances its lastIndex, so reusing CITE_SPLIT here would make alternate
 *  calls return false and citations would render as plain text at random. */
const IS_CITE = /^\[Exhibit\s+[^\]]+\]$/

export function LetterPanel({
  sentences,
  criterion,
  editedText,
  focusedSub,
  argumentTitles,
  staleNodeIds,
  generating,
  onCiteClick,
  onRegenerate,
  onEdit,
  registerParaRef,
}: Props) {
  const { t } = useTranslation()

  const plainText = useMemo(() => sentences.map((s) => s.text).join(' '), [sentences])

  const reporter = useMemo(
    () => new EditReporter(
      'letter',
      (payload) => logger.log('text_edit', payload),
      plainText,
      // Seeded with the server's sent_ids so the lineage in the log is in the
      // same id space as the draft snapshot and the probe (红线 #2). Minting
      // fresh ids here left the two unjoinable.
      sentences,
    ),
    // Recreated only when a NEW letter is generated: the reporter holds the
    // sentence list lineage is measured against, so rebuilding it mid-edit
    // would break the chain (红线 #2).
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [plainText],
  )
  useEffect(() => () => reporter.flushNow(), [reporter])

  // Group by node, preserving generation order.
  const groups = useMemo(() => {
    const out: { argId: string; nodeId: string; sentences: LetterSentence[] }[] = []
    for (const s of sentences) {
      const last = out[out.length - 1]
      if (last && last.nodeId === s.subargument_id) last.sentences.push(s)
      else out.push({ argId: s.argument_id, nodeId: s.subargument_id, sentences: [s] })
    }
    return out
  }, [sentences])

  const stale = staleNodeIds.length

  return (
    <aside
      className="panel bg-white border-l border-slate-200"
      style={{ gridTemplateRows: stale > 0 ? 'auto auto minmax(0,1fr)' : 'auto minmax(0,1fr)' }}
    >
      <div className="phead" style={{ justifyContent: 'space-between' }}>
        <span className="text-[13.5px] font-bold text-slate-700">
          {t('letter.title', { criterion: criterion || t('app.criterion') })}
        </span>
        <button
          onClick={onRegenerate}
          disabled={generating}
          className="text-[12px] text-slate-400 flex items-center gap-1.5 hover:text-slate-600 disabled:opacity-40"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.6" viewBox="0 0 24 24">
            <path d="M16 9h5V4M3 15v5h5M4 9a8 8 0 0113-3l4 3M20 15a8 8 0 01-13 3l-4-3" />
          </svg>
          {/* Nothing has been written yet the first time this is pressed, and
              "Regenerate" above an empty panel reads like a retry of something
              that already happened. */}
          {sentences.length === 0 ? t('letter.generateFirst') : t('letter.regenAll')}
        </button>
      </div>

      {stale > 0 && (
        <div
          className="flex items-center gap-2 px-4 bg-amber-50 border-b border-amber-200"
          style={{ height: 'var(--h-status)' }}
        >
          <span className="w-1.5 h-1.5 rounded-full bg-amber-500 flex-shrink-0" />
          <span className="text-[12px] text-amber-800 truncate">{t('letter.stale', { n: stale })}</span>
          <button
            onClick={onRegenerate}
            disabled={generating}
            className="ml-auto text-[12px] text-amber-900 font-semibold underline underline-offset-2 flex-shrink-0 disabled:opacity-40"
          >
            {t('letter.regen')}
          </button>
        </div>
      )}

      {editedText !== null ? (
        <div className="px-5 py-4 overflow-hidden">
          <textarea
            id="editor"
            spellCheck={false}
            value={editedText}
            onChange={(e) => {
              onEdit(e.target.value)
              reporter.onChange(e.target.value)
            }}
            onBlur={() => reporter.flushNow()}
            onFocus={() => logger.log('panel_focus', { panel: 'letter' })}
          />
        </div>
      ) : (
        <div className="scroll px-5 py-4" onDoubleClick={() => onEdit(plainText)}>
          {sentences.length === 0 && (
            <p className="text-[12.5px] text-slate-400">
              {generating ? t('phase.generation') : t('letter.notYet')}
            </p>
          )}

          {groups.map((group, gi) => {
            const heading =
              gi === 0 || groups[gi - 1].argId !== group.argId
                ? argumentTitles[group.argId]
                : null
            return (
              <div key={`${group.nodeId}-${gi}`}>
                {heading && (
                  <h2 className="text-[15px] font-semibold mb-2.5">
                    {heading.index} {heading.title}
                  </h2>
                )}
                <div
                  ref={(el) => registerParaRef(group.nodeId, el)}
                  className={`para mb-2.5${focusedSub === group.nodeId ? ' is-focus' : ''}`}
                  data-sub={group.nodeId}
                >
                  <p className="text-[13px] leading-[1.8] text-slate-800">
                    {group.sentences.map((s) => (
                      <span key={s.sent_id}>
                        {s.text.split(CITE_SPLIT).map((part, i) =>
                          IS_CITE.test(part) ? (
                            <span
                              key={i}
                              className="cite"
                              role="button"
                              tabIndex={0}
                              onClick={() => onCiteClick(s.snippet_ids[0])}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') onCiteClick(s.snippet_ids[0])
                              }}
                            >
                              {part}
                            </span>
                          ) : (
                            <span key={i}>{part}</span>
                          ),
                        )}{' '}
                      </span>
                    ))}
                  </p>
                </div>
              </div>
            )
          })}

          {sentences.length > 0 && (
            <p className="text-[11px] text-slate-400 mt-4">{t('letter.editHint')}</p>
          )}
        </div>
      )}
    </aside>
  )
}
