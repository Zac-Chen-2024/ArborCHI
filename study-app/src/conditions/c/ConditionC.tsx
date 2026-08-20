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
import { logger, startDwell } from '../../lib/logger'
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
  // Where the viewer is actually pointed. This is its OWN state, not something
  // derived from the focused snippet: the participant can navigate away by
  // hand (exhibit chips, pager) while the focus stays where it was, and the
  // analysis needs those to be two separate facts.
  const [exhibit, setExhibit] = useState('B1')
  const [page, setPage] = useState(2)
  const [zoom, setZoom] = useState(1)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [lightboxZoom, setLightboxZoom] = useState<LightboxZoom>(3)
  // The magnifier keeps its own page so the participant can read around the
  // citation without moving the panel behind it.
  const [lightboxPage, setLightboxPage] = useState(2)
  const [helpOpen, setHelpOpen] = useState(false)

  const subRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const closeDwell = useRef<(() => void) | null>(null)
  const hoverDwell = useRef<(() => void) | null>(null)
  const paraRefs = useRef<Record<string, HTMLDivElement | null>>({})

  const effectiveChip = previewChip ?? committedChip
  const snippet = SNIPPETS[effectiveChip]
  const focusedSub = SNIPPETS[committedChip]?.sub ?? null

  // Where the viewer is pointed right now. A hover PREVIEW takes the panel to
  // the previewed passage without disturbing `exhibit`/`page`, so letting go
  // returns you exactly where you were -- that is what makes preview a look
  // rather than a move (C-05). Manual navigation and committed clicks write to
  // the state; hover never does.
  const viewExhibit = previewChip ? snippet.ex : exhibit
  const viewPage = previewChip ? snippet.page : page
  const showLinkage = viewExhibit === snippet.ex && viewPage === snippet.page

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
    logger.log(via === 'linkage' ? 'cite_click' : 'chip_click', {
      snippet_id: chipId,
      exhibit: target.ex,
      page: target.page,
      label: target.label,
      node_id: target.sub,
      via,
    })
    logger.log('page_change', {
      exhibit: target.ex,
      page: target.page,
      via: 'linkage',
      reason: via === 'linkage' ? 'citation' : 'evidence chip',
    })
    setCommittedChip(chipId)
    setPreviewChip(null)
    setExhibit(target.ex)
    setPage(target.page)
    setLightboxPage(target.page)
    // Scroll the matching letter paragraph into view; the sub-argument card and
    // the breadcrumb follow from `committedChip` on the next render.
    paraRefs.current[target.sub]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    if (via === 'linkage') subRefs.current[target.sub]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [])

  const focusSub = useCallback((subId: string) => {
    const first = Object.values(SNIPPETS).find((s) => s.sub === subId)
    if (first) commitChip(first.id, 'click')
  }, [commitChip])

  const accept = (subId: string) => {
    const before = tree.flatMap((a) => a.subs).find((s) => s.id === subId)
    logger.log('node_state', {
      node_id: subId,
      node_title: before?.title,
      from: before?.state,
      to: 'accepted',
      via: 'button',
    })
    setTree((prev) =>
      prev.map((a) => ({
        ...a,
        subs: a.subs.map((s) => (s.id === subId ? { ...s, state: 'accepted' as const } : s)),
      })),
    )
  }

  const acceptAll = () => {
    // Logged per node, not as one "accept all": the analysis asks how many
    // nodes a participant accepted without ever looking at them, and a single
    // aggregate event would erase that.
    tree.flatMap((a) => a.subs)
      .filter((s) => s.state === 'proposed')
      .forEach((s) =>
        logger.log('node_state', {
          node_id: s.id,
          node_title: s.title,
          from: s.state,
          to: 'accepted',
          via: 'accept_all',
        }),
      )
    setTree((prev) => prev.map((a) => ({ ...a, subs: a.subs.map((s) => ({ ...s, state: 'accepted' as const })) })))
  }

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
      openLightbox(SNIPPETS[committedChip].page, 'keyboard')
    }
  }

  /** Single entry point for the magnifier so that open/close always pair and
      the dwell time is always measured (C-11). */
  const openLightbox = useCallback((atPage: number, via: string) => {
    const s = SNIPPETS[committedChip]
    logger.log('lightbox_open', {
      snippet_id: committedChip,
      exhibit: s.ex,
      page: atPage,
      cited_page: s.page,
      label: s.label,
      via,
    })
    closeDwell.current = startDwell('lightbox_close', {
      snippet_id: committedChip,
      exhibit: s.ex,
      page: atPage,
    })
    setLightboxPage(atPage)
    setLightboxOpen(true)
  }, [committedChip])

  const closeLightbox = useCallback(() => {
    closeDwell.current?.()
    closeDwell.current = null
    setLightboxOpen(false)
  }, [])

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
        onHelp={() => {
          logger.log('panel_focus', { panel: 'topbar', target: 'help' })
          setHelpOpen((v) => !v)
        }}
        onSubmit={() => logger.log('declare_done', { condition: 'c' })}
      />

      <div id="main">
        <aside
          className="panel bg-white border-r border-slate-200"
          style={{ gridTemplateRows: 'auto auto auto minmax(0,1fr) auto auto' }}
        >
          <EvidenceViewer
            exhibits={EXHIBITS}
            activeExhibit={viewExhibit}
            page={viewPage}
            zoom={zoom}
            // The highlight belongs to a place, not to a selection: once the
            // participant has navigated somewhere else by hand, drawing the
            // focused snippet's box on THIS page would be pointing at the
            // wrong text. Show it only where it actually lives.
            linkage={showLinkage ? { snippet, preview: previewChip !== null } : undefined}
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
            onOpenLightbox={() => openLightbox(viewPage, 'page_button')}
            onExhibitClick={(id) => {
              logger.log('doc_open', { exhibit: id, from_exhibit: exhibit, via: 'chip' })
              logger.log('page_change', { exhibit: id, page: 1, via: 'click', reason: 'exhibit chip' })
              setExhibit(id)
              setPage(1)
            }}
            onPageChange={(p, via) => {
              logger.log('page_change', { exhibit, page: p, from_page: page, via })
              setPage(p)
            }}
            onZoom={(z) => {
              logger.log('zoom', { panel: 'evidence', from: zoom, to: z })
              setZoom(z)
            }}
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
          onChipHoverStart={(id) => {
            if (id === committedChip) return
            const s = SNIPPETS[id]
            // hover_start / hover_end are a LOOK; chip_click is a CHOICE. The
            // whole point of the pair is that the analysis can tell how much
            // evidence a participant inspected but did not act on (C-05).
            logger.log('hover_start', {
              snippet_id: id, exhibit: s.ex, page: s.page, label: s.label, node_id: s.sub,
            })
            hoverDwell.current = startDwell('hover_end', {
              snippet_id: id, exhibit: s.ex, page: s.page, label: s.label,
            })
            setPreviewChip(id)
          }}
          onChipHoverEnd={() => {
            hoverDwell.current?.()
            hoverDwell.current = null
            setPreviewChip(null)
          }}
          onChipClick={(id) => commitChip(id, 'click')}
          onChipZoom={(id) => {
            commitChip(id, 'click')
            openLightbox(SNIPPETS[id].page, 'chip_magnifier')
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
            openLightbox(SNIPPETS[id].page, 'citation')
          }}
          onRegenerate={() => logger.log('generate_trigger', { scope: 'paragraph' })}
          registerParaRef={(sub, el) => {
            paraRefs.current[sub] = el
          }}
        />
      </div>

      <Lightbox
        open={lightboxOpen}
        snippet={SNIPPETS[committedChip]}
        page={lightboxPage}
        zoom={lightboxZoom}
        crumb={crumb}
        onZoom={setLightboxZoom}
        onClose={closeLightbox}
        onPage={(p) => {
          logger.log('page_change', {
            exhibit: SNIPPETS[committedChip].ex,
            page: p,
            from_page: lightboxPage,
            via: 'click',
            surface: 'lightbox',
          })
          setLightboxPage(p)
        }}
      />

      <HelpDrawer open={helpOpen} condition="c" onClose={() => setHelpOpen(false)} />
    </div>
  )
}
