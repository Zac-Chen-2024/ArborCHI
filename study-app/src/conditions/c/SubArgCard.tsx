/**
 * Sub-argument card (C-03). The state machine lives in the `data-state`
 * attribute so the CSS copied from the mockup drives the whole appearance:
 *
 *   proposed  dashed amber, shows the "AI suggested" pill and the Accept row
 *   accepted  solid green, shows the done dot and the lone menu button
 *   edited    solid green plus the "Renamed" tag
 *
 * 红线 #5 / C-14: nothing here reflects whether a node is a distractor. The
 * backend does not send such a flag and this component has nowhere to put one
 * -- keep it that way. Adding a `data-*` attribute for "AI confidence" or
 * similar would leak the judgement the study measures.
 */
import { useTranslation } from 'react-i18next'

import type { SubArgument } from '../../data/fixtures'
import { SNIPPETS } from '../../data/fixtures'
import { GRAB_HANDLE, MENU_DOTS } from '../../lib/glyphs'
import { SnippetChip } from './SnippetChip'

interface Props {
  sub: SubArgument
  focused: boolean
  committedChip: string | null
  previewChip: string | null
  onFocus: () => void
  onAccept: () => void
  onChipHoverStart: (id: string) => void
  onChipHoverEnd: () => void
  onChipClick: (id: string) => void
  onChipZoom: (id: string) => void
  registerRef: (el: HTMLDivElement | null) => void
}

export function SubArgCard({
  sub,
  focused,
  committedChip,
  previewChip,
  onFocus,
  onAccept,
  onChipHoverStart,
  onChipHoverEnd,
  onChipClick,
  onChipZoom,
  registerRef,
}: Props) {
  const { t } = useTranslation()

  return (
    <div
      ref={registerRef}
      className={`sub${focused ? ' is-focus' : ''}`}
      data-sub={sub.id}
      data-state={sub.state}
      role="treeitem"
      aria-level={2}
      aria-selected={focused}
      tabIndex={0}
      onClick={onFocus}
    >
      <div className="flex items-center gap-2">
        <span className="grab text-slate-300 text-[13px] select-none" aria-hidden="true" title={t('node.drag')}>
          {GRAB_HANDLE}
        </span>
        <span className="done-dot w-2.5 h-2.5 rounded-full bg-emerald-500 flex-shrink-0" />
        <p className="text-[13.5px] font-semibold truncate">{sub.title}</p>
        {sub.renamed && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500 flex-shrink-0">
            {t('node.renamed')}
          </span>
        )}
        <span className="ai-pill text-[9.5px] font-bold px-1.5 py-0.5 rounded bg-amber-100 text-amber-700">
          {t('node.aiPill')}
        </span>
        <div className="accept-row ml-auto items-center gap-2">
          <button
            className="px-3 py-1.5 rounded-md bg-emerald-600 text-white text-[12px] font-semibold"
            onClick={(e) => {
              e.stopPropagation()
              onAccept()
            }}
          >
            {t('node.accept')}
          </button>
          <button className="text-slate-400 text-[13px] px-1" aria-label={t('node.menuSub')}>
            {MENU_DOTS}
          </button>
        </div>
        <button className="menu-solo text-slate-400 text-[13px] px-1 flex-shrink-0 ml-auto" aria-label={t('node.menuSub')}>
          {MENU_DOTS}
        </button>
      </div>

      <div className="flex flex-wrap gap-2 mt-2.5 ml-5">
        {sub.snippetIds.map((id) => (
          <SnippetChip
            key={id}
            snippet={SNIPPETS[id]}
            committed={committedChip === id}
            previewing={previewChip === id}
            onHoverStart={() => onChipHoverStart(id)}
            onHoverEnd={onChipHoverEnd}
            onClick={() => onChipClick(id)}
            onZoom={() => onChipZoom(id)}
          />
        ))}
      </div>
    </div>
  )
}
