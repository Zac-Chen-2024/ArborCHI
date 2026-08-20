/**
 * The ⋯ menu on a sub-argument card (C-04).
 *
 * Every item routes to `useTree`, which logs the operation with its before and
 * after state. Nothing here calls the logger directly -- if it did, an item
 * added later could quietly skip it.
 *
 * "Move under…" opens a second level listing the other arguments, because a
 * move needs a destination and a flat menu has nowhere to put one.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { MENU_DOTS } from '../../lib/glyphs'
import { useTree } from '../../lib/treeStore'

interface Props {
  nodeId: string
  parentId: string
  canMergeUp: boolean
  /** Renaming happens inline on the card, not here. `window.prompt` was the
   *  first version and was wrong twice over: a native dialog looks nothing
   *  like the rest of the interface, and it blocks the page, which makes the
   *  whole flow untestable in a browser harness. */
  onStartRename: () => void
}

export function NodeMenu({ nodeId, parentId, canMergeUp, onStartRename }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [moving, setMoving] = useState(false)
  const ref = useRef<HTMLDivElement | null>(null)
  const tree = useTree()

  useEffect(() => {
    if (!open) return
    const onAway = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setMoving(false)
      }
    }
    document.addEventListener('mousedown', onAway)
    return () => document.removeEventListener('mousedown', onAway)
  }, [open])

  const run = (fn: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation()
    fn()
    setOpen(false)
    setMoving(false)
  }

  const item = 'w-full text-left px-3 py-1.5 text-[12.5px] text-slate-700 hover:bg-slate-50'

  return (
    <div className="relative flex-shrink-0" ref={ref}>
      <button
        className="text-slate-400 text-[13px] px-1"
        aria-label={t('node.menuSub')}
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((v) => !v)
        }}
      >
        {MENU_DOTS}
      </button>

      {open && (
        <div className="absolute right-0 top-6 z-30 w-[200px] rounded-lg border border-slate-200 bg-white shadow-lg py-1">
          {!moving ? (
            <>
              <button className={item} onClick={run(onStartRename)}>
                {t('node.menu.rename')}
              </button>
              <button className={item} onClick={run(() => tree.splitNode(nodeId))}>
                {t('node.menu.split')}
              </button>
              <button
                className={`${item} disabled:opacity-40`}
                disabled={!canMergeUp}
                onClick={run(() => tree.mergeUp(nodeId))}
              >
                {t('node.menu.mergeUp')}
              </button>
              <button
                className={item}
                onClick={(e) => {
                  e.stopPropagation()
                  setMoving(true)
                }}
              >
                {t('node.menu.moveTo')}
              </button>
              <button className={item} onClick={run(() => tree.promote(nodeId))}>
                {t('node.menu.promote')}
              </button>
              <div className="h-px bg-slate-100 my-1" />
              <button
                className={`${item} text-rose-600`}
                onClick={run(() => tree.remove(nodeId))}
              >
                {t('node.menu.remove')}
              </button>
            </>
          ) : (
            tree.args
              .filter((a) => a.id !== parentId)
              .map((a) => (
                <button key={a.id} className={item} onClick={run(() => tree.moveTo(nodeId, a.id))}>
                  {a.index} {a.title}
                </button>
              ))
          )}
        </div>
      )}
    </div>
  )
}
