/**
 * The nested-card tree (C-03/C-04/C-06/C-12).
 *
 * Two levels, deliberately: the outer container is an argument, the inner
 * cards are sub-arguments. This is the shape the mockup fixes, and it is not a
 * canvas -- the product frontend's ArgumentGraph does not come along (§7.5).
 *
 * All mutation goes through `useTree`, never through local state, because that
 * is where the before/after logging happens.
 */
import { useTranslation } from 'react-i18next'

import type { Snippet } from '../../lib/material'
import { GRAB_HANDLE, MENU_DOTS } from '../../lib/glyphs'
import { logger } from '../../lib/logger'
import { useTree } from '../../lib/treeStore'
import { SubArgCard } from './SubArgCard'

interface Props {
  snippets: Record<string, Snippet>
  /** Snippets no node currently cites (C-06). */
  unusedSnippetIds: string[]
  focusedSub: string | null
  committedChip: string | null
  previewChip: string | null
  onFocusSub: (id: string) => void
  onChipHoverStart: (id: string) => void
  onChipHoverEnd: () => void
  onChipClick: (id: string) => void
  onChipZoom: (id: string) => void
  registerSubRef: (id: string, el: HTMLDivElement | null) => void
}

export function TreePanel(props: Props) {
  const { t } = useTranslation()
  const tree = useTree()

  const live = tree.args.flatMap((a) => a.subs).filter((s) => s.state !== 'removed')
  const counts = {
    args: tree.args.length,
    subs: live.length,
    evidence: live.reduce((n, s) => n + s.snippet_ids.length, 0),
    proposed: live.filter((s) => s.state === 'proposed').length,
    accepted: live.filter((s) => s.state === 'accepted').length,
  }

  return (
    <section className="panel bg-slate-100" style={{ gridTemplateRows: 'auto minmax(0,1fr)' }}>
      <div className="phead" style={{ padding: '0 20px' }}>
        <span className="text-[13.5px] font-bold text-slate-700 flex-shrink-0">{t('tree.title')}</span>
        <span className="text-[12px] text-slate-400 truncate hidden lg:inline">
          {t('tree.stats', { a: counts.args, s: counts.subs, e: counts.evidence })}
        </span>
        <div className="ml-auto flex items-center gap-2 flex-shrink-0">
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-amber-50 border border-amber-200 text-amber-700 text-[11.5px] font-medium num">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            {t('tree.pending', { n: counts.proposed })}
          </span>
          <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-50 border border-emerald-200 text-emerald-700 text-[11.5px] font-medium num">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            {t('tree.accepted', { n: counts.accepted })}
          </span>
          <button
            onClick={() => tree.acceptAll()}
            className="px-2.5 py-1 rounded-md border border-slate-200 text-slate-500 text-[11.5px] font-medium hover:bg-slate-50"
          >
            {t('tree.acceptAll')}
          </button>
        </div>
      </div>

      <div className="scroll p-4" role="tree" aria-label={t('tree.title')}>
        {tree.args.map((arg) => {
          const visible = arg.subs.filter((s) => s.state !== 'removed')
          return (
            <div
              key={arg.id}
              className="rounded-xl border-2 border-emerald-500 bg-white overflow-hidden shadow-sm mb-3.5"
              role="treeitem"
              aria-level={1}
              aria-expanded="true"
            >
              <div className="px-4 py-2.5 flex items-center gap-2.5 bg-emerald-50 border-b border-emerald-200">
                <span
                  className="rounded-full bg-emerald-500 flex items-center justify-center flex-shrink-0"
                  style={{ width: 18, height: 18 }}
                >
                  <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" strokeWidth="3.5" viewBox="0 0 24 24">
                    <path d="M5 13l4 4L19 7" />
                  </svg>
                </span>
                <div className="min-w-0">
                  <p className="text-[14px] font-bold truncate">
                    {arg.index} {arg.title}
                  </p>
                  {arg.rationale && (
                    <p className="text-[11px] text-emerald-700/70 truncate">{arg.rationale}</p>
                  )}
                </div>
                <span className="ml-auto text-[11.5px] text-slate-400 flex-shrink-0">
                  {t('tree.subCount', { n: visible.length })}
                </span>
                <span className="grab text-slate-300 text-[14px] select-none flex-shrink-0" aria-hidden="true">
                  {GRAB_HANDLE}
                </span>
                <button className="text-slate-400 text-[14px] px-1 flex-shrink-0" aria-label={t('node.menuArgument')}>
                  {MENU_DOTS}
                </button>
              </div>

              <div className="p-2.5 space-y-2" role="group">
                {arg.subs.map((sub, i) => (
                  <SubArgCard
                    key={sub.id}
                    sub={sub}
                    parentId={arg.id}
                    canMergeUp={i > 0}
                    snippets={props.snippets}
                    focused={props.focusedSub === sub.id}
                    committedChip={props.committedChip}
                    previewChip={props.previewChip}
                    onFocus={() => props.onFocusSub(sub.id)}
                    onAccept={() => tree.setState(sub.id, 'accepted', 'button')}
                    onChipHoverStart={props.onChipHoverStart}
                    onChipHoverEnd={props.onChipHoverEnd}
                    onChipClick={props.onChipClick}
                    onChipZoom={props.onChipZoom}
                    registerRef={(el) => props.registerSubRef(sub.id, el)}
                  />
                ))}
                <button
                  onClick={() => tree.addSub(arg.id)}
                  className="text-[12px] text-slate-500 font-medium ml-1 hover:text-slate-700"
                >
                  {t('node.addSub', { arg: arg.index })}
                </button>
              </div>
            </div>
          )
        })}

        <div className="flex items-stretch gap-3">
          <button className="flex-1 py-2.5 rounded-xl border-2 border-dashed border-slate-300 bg-white/60 text-[12.5px] text-slate-500 font-medium hover:border-slate-400">
            {t('tree.newArgument')}
          </button>
          <div className="w-[280px] rounded-xl border border-slate-200 bg-white px-3.5 py-2.5">
            <p className="text-[11.5px] font-bold text-slate-500 mb-1.5">
              {t('pool.title', { n: props.unusedSnippetIds.length })}
            </p>
            <div className="flex flex-wrap gap-1.5">
              {props.unusedSnippetIds.map((id) => {
                const s = props.snippets[id]
                if (!s) return null
                return (
                  <button
                    key={id}
                    onClick={() => {
                      logger.log('pool_drag_out', {
                        snippet_id: id, exhibit: s.exhibit, page: s.page, label: s.label,
                      })
                      props.onChipClick(id)
                    }}
                    className="grab inline-flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-slate-50 border border-slate-200 text-[11.5px] text-slate-600"
                  >
                    <span className="mono text-[10.5px] text-slate-400 font-semibold">
                      {t('ref.exPage', { ex: s.exhibit, i: s.page })}
                    </span>{' '}
                    {s.label}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
