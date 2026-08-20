/**
 * Sub-argument card (C-03). The state machine lives in the `data-state`
 * attribute so the CSS copied from the mockup drives the whole appearance:
 *
 *   proposed  dashed amber, shows the "AI suggested" pill and the Accept row
 *   accepted  solid green, shows the done dot and the lone menu button
 *   edited    solid green plus the "Renamed" tag
 *
 * 红线 #5 / C-14: nothing here reflects whether a node is one the material
 * counts as noise. The backend strips that flag before sending the tree, so
 * this component has nowhere to get it from and nowhere to put it -- keep it
 * that way. An "AI confidence" or "strength" prop would leak the judgement the
 * study exists to measure.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { Snippet } from '../../lib/material'
import { GRAB_HANDLE } from '../../lib/glyphs'
import { useTree, type WorkingSub } from '../../lib/treeStore'
import { NodeMenu } from './NodeMenu'
import { SnippetChip } from './SnippetChip'

interface Props {
  sub: WorkingSub
  parentId: string
  canMergeUp: boolean
  snippets: Record<string, Snippet>
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
  parentId,
  canMergeUp,
  snippets,
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
  const tree = useTree()
  const [renaming, setRenaming] = useState(false)
  const [draftTitle, setDraftTitle] = useState(sub.title)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    if (renaming) inputRef.current?.select()
  }, [renaming])

  const commitRename = () => {
    setRenaming(false)
    // The store decides whether this is a change at all; a rename to the same
    // string must not produce a tree_op saying something happened.
    tree.rename(sub.id, draftTitle.trim())
  }

  // A newly created node arrives with an empty title and opens straight into
  // the editor -- otherwise the participant has to find the menu to name the
  // thing they just made.
  useEffect(() => {
    if (sub.title === '') {
      setDraftTitle('')
      setRenaming(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sub.id])

  // A removed node stays in the tree data (the server must be told it was
  // removed) but leaves the screen.
  if (sub.state === 'removed') return null

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
        {renaming ? (
          <input
            ref={inputRef}
            value={draftTitle}
            autoFocus
            onChange={(e) => setDraftTitle(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            onBlur={commitRename}
            onKeyDown={(e) => {
              e.stopPropagation()
              if (e.key === 'Enter') commitRename()
              if (e.key === 'Escape') {
                setDraftTitle(sub.title)
                setRenaming(false)
              }
            }}
            placeholder={t('node.untitled')}
            className="text-[13.5px] font-semibold flex-1 min-w-0 px-1.5 py-0.5 rounded border border-emerald-400 outline-none"
          />
        ) : (
          <p
            className="text-[13.5px] font-semibold truncate"
            onDoubleClick={(e) => {
              e.stopPropagation()
              setDraftTitle(sub.title)
              setRenaming(true)
            }}
          >
            {sub.title || t('node.untitled')}
          </p>
        )}
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
          <NodeMenu
            nodeId={sub.id}
            parentId={parentId}
            canMergeUp={canMergeUp}
            onStartRename={() => {
              setDraftTitle(sub.title)
              setRenaming(true)
            }}
          />
        </div>
        <div className="menu-solo ml-auto flex-shrink-0">
          <NodeMenu
            nodeId={sub.id}
            parentId={parentId}
            canMergeUp={canMergeUp}
            onStartRename={() => {
              setDraftTitle(sub.title)
              setRenaming(true)
            }}
          />
        </div>
      </div>

      <div className="flex flex-wrap gap-2 mt-2.5 ml-5">
        {sub.snippet_ids
          .filter((id) => snippets[id])
          .map((id) => (
            <SnippetChip
              key={id}
              snippet={snippets[id]}
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
