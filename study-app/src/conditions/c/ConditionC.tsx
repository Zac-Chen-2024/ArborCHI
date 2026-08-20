/**
 * Condition C -- Arbor. Layout mirrors mockups/arbor-write-mode-v5.html.
 *
 * The linkage state machine lives here so that all four panels move together
 * in one place:
 *
 *   committedChip   set by a click; survives mouse-out; drives everything
 *   previewChip     set by hover; reverts on mouse-out; drives the left panel
 *                   and the "Hover preview" tag only
 *
 * `effective` is what the evidence panel shows: the preview when there is one,
 * otherwise the committed choice. That single line is the difference between
 * "looked at" and "chose", and the log distinguishes them (C-05).
 */
import { useCallback, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EvidenceViewer } from '../../components/shared/EvidenceViewer'
import { Lightbox, type LightboxZoom } from '../../components/shared/Lightbox'
import { TopBar } from '../../components/shared/TopBar'
import { EXHIBITS, SNIPPETS, TREE, type Argument } from '../../data/fixtures'
import type { StudyState } from '../../lib/api'
import { CRUMB_SEP } from '../../lib/glyphs'
import { visibleRemainingMs } from '../../lib/session'
import { HelpDrawer } from '../common/HelpDrawer'
import { LetterPanel } from './LetterPanel'
import { RelationsPanel } from './RelationsPanel'
import { TreePanel } from './TreePanel'
import './c.css'

interface Props {
  state: StudyState
}

export function ConditionC({ state }: Props) {
  const { t } = useTranslation()

  const [tree, setTree] = useState<Argument[]>(TREE)
  const [committedChip, setCommittedChip] = useState<string>('c4')
  const [previewChip, setPreviewChip] = useState<string | null>(null)
  const [page, setPage] = useState(2)
  const [zoom, setZoom] = useState(1)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [lightboxZoom, setLightboxZoom] = useState<LightboxZoom>(3)
  const [helpOpen, setHelpOpen] = useState(false)

  const subRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const paraRefs = useRef<Record<string, HTMLDivElement | null>>({})

  const effectiveChip = previewChip ?? committedChip
  const snippet = SNIPPETS[effectiveChip]
  const focusedSub = SNIPPETS[committedChip]?.sub ?? null

  const subTitle = useMemo(() => {
    const flat = tree.flatMap((a) => a.subs.map((s) => [s.id, s.title] as const))
    return Object.fromEntries(flat)
  }, [tree])

  const argOf = useMemo(() => {
    const pairs = tree.flatMap((a) => a.subs.map((s) => [s.id, `${a.index} ${a.title}`] as const))
    return Object.fromEntries(pairs)
  }, [tree])

  /** Commit a focus: the four-step trace-back (C-08). */
  const commitChip = useCallback((chipId: string, via: 'click' | 'linkage') => {
    const target = SNIPPETS[chipId]
    if (!target) return
    setCommittedChip(chipId)
    setPreviewChip(null)
    setPage(target.page)
    // Scroll the matching letter paragraph into view; the sub-argument card and
    // the breadcrumb follow from `committedChip` on the next render.
    paraRefs.current[target.sub]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    if (via === 'linkage') subRefs.current[target.sub]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [])

  const focusSub = useCallback((subId: string) => {
    const first = Object.values(SNIPPETS).find((s) => s.sub === subId)
    if (first) commitChip(first.id, 'click')
  }, [commitChip])

  const accept = (subId: string) =>
    setTree((prev) =>
      prev.map((a) => ({
        ...a,
        subs: a.subs.map((s) => (s.id === subId ? { ...s, state: 'accepted' as const } : s)),
      })),
    )

  const acceptAll = () =>
    setTree((prev) => prev.map((a) => ({ ...a, subs: a.subs.map((s) => ({ ...s, state: 'accepted' as const })) })))

  // Keyboard: arrows move focus, Enter accepts, v opens the magnifier (C-12).
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (lightboxOpen) return
    const flat = tree.flatMap((a) => a.subs)
    const i = flat.findIndex((s) => s.id === focusedSub)
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const next = flat[Math.min(flat.length - 1, Math.max(0, i + (e.key === 'ArrowDown' ? 1 : -1)))]
      if (next) {
        subRefs.current[next.id]?.focus()
        focusSub(next.id)
      }
    }
    if (e.key === 'Enter' && focusedSub && flat[i]?.state === 'proposed') {
      e.preventDefault()
      accept(focusedSub)
    }
    if (e.key.toLowerCase() === 'v' && focusedSub) {
      e.preventDefault()
      setLightboxOpen(true)
    }
  }

  const crumb = (
    <>
      <span className="px-1.5 py-0.5 rounded bg-slate-100">{argOf[snippet.sub]}</span>
      <span className="text-slate-300">{CRUMB_SEP}</span>
      <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 font-medium">{subTitle[snippet.sub]}</span>
      <span className="text-slate-300">{CRUMB_SEP}</span>
      <span className="mono px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 font-semibold">
        {t('ref.exPage', { ex: snippet.ex, i: snippet.page })}
      </span>
    </>
  )

  const phaseLabel =
    state.phase === 'organization' ? t('phase.organization') : t('phase.verify')

  return (
    <div id="app" onKeyDown={onKeyDown}>
      <TopBar
        condition="c"
        track={state.track}
        phaseLabel={phaseLabel}
        remainingMs={visibleRemainingMs(state)}
        onHelp={() => setHelpOpen((v) => !v)}
        onSubmit={() => undefined}
      />

      <div id="main">
        <aside
          className="panel bg-white border-r border-slate-200"
          style={{ gridTemplateRows: 'auto auto auto minmax(0,1fr) auto auto' }}
        >
          <EvidenceViewer
            exhibits={EXHIBITS}
            activeExhibit={snippet.ex}
            page={page}
            zoom={zoom}
            linkage={{ snippet, preview: previewChip !== null }}
            title={t('evidence.titleC')}
            headerBadge={
              previewChip !== null ? (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-600 font-semibold">
                  {t('crumb.preview')}
                </span>
              ) : null
            }
            contextStrip={
              <div className="ctxstrip">
                <p className="text-[10px] font-bold text-slate-400 tracking-widest flex-shrink-0">{t('crumb.label')}</p>
                <div className="flex items-center gap-1.5 text-[11px] text-slate-600 flex-nowrap overflow-hidden whitespace-nowrap min-w-0">
                  {crumb}
                </div>
              </div>
            }
            onOpenLightbox={() => setLightboxOpen(true)}
            onExhibitClick={(id) => {
              const first = Object.values(SNIPPETS).find((s) => s.ex === id)
              if (first) setPage(first.page)
            }}
            onPageChange={(p) => setPage(p)}
            onZoom={setZoom}
          />
          <RelationsPanel snippet={snippet} onMentionClick={() => undefined} />
        </aside>

        <TreePanel
          tree={tree}
          focusedSub={focusedSub}
          committedChip={committedChip}
          previewChip={previewChip}
          onFocusSub={focusSub}
          onAccept={accept}
          onAcceptAll={acceptAll}
          onChipHoverStart={(id) => id !== committedChip && setPreviewChip(id)}
          onChipHoverEnd={() => setPreviewChip(null)}
          onChipClick={(id) => commitChip(id, 'click')}
          onChipZoom={(id) => {
            commitChip(id, 'click')
            setLightboxOpen(true)
          }}
          registerSubRef={(id, el) => {
            subRefs.current[id] = el
          }}
        />

        <LetterPanel
          focusedSub={focusedSub}
          staleCount={1}
          onCiteClick={(id) => {
            commitChip(id, 'linkage')
            setLightboxOpen(true)
          }}
          onRegenerate={() => undefined}
          registerParaRef={(sub, el) => {
            paraRefs.current[sub] = el
          }}
        />
      </div>

      <Lightbox
        open={lightboxOpen}
        snippet={SNIPPETS[committedChip]}
        zoom={lightboxZoom}
        crumb={crumb}
        onZoom={setLightboxZoom}
        onClose={() => setLightboxOpen(false)}
        onPage={setPage}
      />

      <HelpDrawer open={helpOpen} condition="c" onClose={() => setHelpOpen(false)} />
    </div>
  )
}
