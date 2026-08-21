/**
 * Condition C -- Arbor. Layout mirrors mockups/arbor-write-mode-v5.html.
 *
 * ## The linkage state machine
 *
 *   committedChip   set by a click; survives mouse-out; drives all four panels
 *   previewChip     set by hover; reverts on mouse-out; moves the view only
 *
 * `viewExhibit`/`viewPage` are where the evidence panel is pointed. A hover
 * PREVIEW takes the panel somewhere without writing that state, so letting go
 * returns you exactly where you were -- which is what makes a preview a look
 * rather than a move, and why the log keeps two separate events for it (C-05).
 *
 * ## Generation
 *
 * Fires once on entering the generation phase, and after that only when the
 * participant asks. Never as a side effect of a render: the server writes the
 * initial snapshot on every call (红线 #1), so an unrequested generation would
 * put a second baseline in the record with no event explaining it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EvidenceViewer } from '../../components/shared/EvidenceViewer'
import { Lightbox, type LightboxZoom } from '../../components/shared/Lightbox'
import { TopBar } from '../../components/shared/TopBar'
import type { StudyState } from '../../lib/api'
import { CRUMB_SEP } from '../../lib/glyphs'
import { logger, startDwell } from '../../lib/logger'
import {
  fetchMaterial, generateLetter, submitFinal,
  type GeneratedLetter, type Material,
} from '../../lib/material'
import { usePractice } from '../../lib/practice'
import { visibleRemainingMs } from '../../lib/session'
import { fetchStoredTree, setTreeMaterial, useTree } from '../../lib/treeStore'
import { HelpDrawer } from '../common/HelpDrawer'
import { PracticeGate } from '../common/PracticeGate'
import { LetterPanel } from './LetterPanel'
import { RelationsPanel } from './RelationsPanel'
import { TreePanel } from './TreePanel'
import './c.css'

interface Props {
  state: StudyState
}

export function ConditionC({ state }: Props) {
  const { t } = useTranslation()
  const tree = useTree()
  const practice = usePractice()
  const inPractice = state.phase === 'practice'

  useEffect(() => {
    if (inPractice) void usePractice.getState().refresh()
  }, [inPractice])

  const [material, setMaterial] = useState<Material | null>(null)
  const [letter, setLetter] = useState<GeneratedLetter | null>(null)
  const [editedText, setEditedText] = useState<string | null>(null)
  const [generating, setGenerating] = useState(false)
  const [generateFailed, setGenerateFailed] = useState(false)

  const [committedChip, setCommittedChip] = useState<string | null>(null)
  const [previewChip, setPreviewChip] = useState<string | null>(null)
  const [exhibit, setExhibit] = useState<string>('')
  const [page, setPage] = useState(1)
  const [zoom, setZoom] = useState(1)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [lightboxZoom, setLightboxZoom] = useState<LightboxZoom>(3)
  const [lightboxPage, setLightboxPage] = useState(1)
  // Which snippet the magnifier is showing. Its own state, set at open time,
  // so the dialog and the log can never disagree about it.
  const [lightboxChip, setLightboxChip] = useState<string | null>(null)
  const [helpOpen, setHelpOpen] = useState(false)

  const subRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const paraRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const closeDwell = useRef<(() => void) | null>(null)
  const hoverDwell = useRef<(() => void) | null>(null)
  const generatedOnce = useRef(false)
  /** The tree the current letter was written from, for stale detection. */
  const generatedFrom = useRef<Record<string, {
    title: string; parent_id: string; snippet_ids: string[]
  }> | null>(null)

  // --- material ------------------------------------------------------------
  useEffect(() => {
    // Refetched on the practice boundary: the server serves a different bundle
    // during practice, so crossing that line means new material and a new tree.
    void (async () => {
      const m = await fetchMaterial()
      setMaterial(m)
      setTreeMaterial(m.material_id)

      // The pristine tree first, then whatever the participant had already
      // made of it. Restoring is not a special case of a crash: it is what
      // happens on any reload, and without it the organisation phase silently
      // reverted to the machine's proposal and the letter was regenerated from
      // it (see lib/treeStore.ts).
      useTree.getState().load(m.tree)
      const saved = await fetchStoredTree()
      if (saved) useTree.getState().hydrate(saved)

      setCommittedChip(null)
      if (m.exhibits[0]) setExhibit(m.exhibits[0].id)
    })()
  }, [inPractice])

  // Memoised: `material?.snippets ?? {}` builds a fresh object on every
  // render, which would make every memo and callback below re-create itself
  // each time and re-render the whole tree.
  const snippets = useMemo(() => material?.snippets ?? {}, [material])
  const effectiveChip = previewChip ?? committedChip
  const snippet = effectiveChip ? snippets[effectiveChip] ?? null : null

  const viewExhibit = previewChip && snippet ? snippet.exhibit : exhibit
  const viewPage = previewChip && snippet ? snippet.page : page
  const showLinkage = !!snippet && viewExhibit === snippet.exhibit && viewPage === snippet.page

  const ownerOf = useCallback(
    (snippetId: string) =>
      tree.args.flatMap((a) => a.subs).find((s) => s.snippet_ids.includes(snippetId)) ?? null,
    [tree.args],
  )

  const focusedSub = useMemo(
    () => (committedChip ? ownerOf(committedChip)?.id ?? null : null),
    [committedChip, ownerOf],
  )

  const argumentTitles = useMemo(
    () => Object.fromEntries(tree.args.map((a) => [a.id, { index: a.index, title: a.title }])),
    [tree.args],
  )
  const nodeTitles = useMemo(
    () => Object.fromEntries(tree.args.flatMap((a) => a.subs.map((s) => [s.id, s.title]))),
    [tree.args],
  )
  const parentTitles = useMemo(
    () => Object.fromEntries(
      tree.args.flatMap((a) => a.subs.map((s) => [s.id, `${a.index} ${a.title}`])),
    ),
    [tree.args],
  )

  const unusedSnippetIds = useMemo(() => {
    const used = new Set(tree.args.flatMap((a) => a.subs.flatMap((s) => s.snippet_ids)))
    return Object.keys(snippets).filter((id) => !used.has(id))
  }, [snippets, tree.args])

  /** Nodes whose paragraph no longer matches the node (C-09).
   *
   * Two ways that happens, and only the first used to be detected: a node with
   * no paragraph at all (added since the last generation), and a node whose
   * paragraph exists but was written from a different title, parent or set of
   * evidence. Renaming and re-parenting are the commonest edits in the
   * organisation phase and both leave the paragraph in place, so the letter
   * quietly stopped matching the structure and the stale banner never
   * appeared -- through the whole verification phase, where the letter under
   * review is the object of the task.
   */
  const staleNodeIds = useMemo(() => {
    if (!letter) return []
    const rendered = new Set(letter.sentences.map((s) => s.subargument_id))
    const from = generatedFrom.current
    const changedSince = (id: string, sub: { title: string; snippet_ids: string[] }, parentId: string) => {
      const was = from?.[id]
      if (!was) return true
      return (
        was.title !== sub.title ||
        was.parent_id !== parentId ||
        JSON.stringify(was.snippet_ids) !== JSON.stringify(sub.snippet_ids)
      )
    }
    return tree.args
      .flatMap((a) => a.subs.map((s) => ({ sub: s, parentId: a.id })))
      .filter(({ sub, parentId }) =>
        sub.state !== 'removed' &&
        (!rendered.has(sub.id) || changedSince(sub.id, sub, parentId)))
      .map(({ sub }) => sub.id)
  }, [letter, tree.args])

  // --- generation ----------------------------------------------------------
  const runGeneration = useCallback(async (trigger: string) => {
    setGenerating(true)
    setGenerateFailed(false)
    logger.log('generate_trigger', { scope: 'letter', trigger })
    try {
      const states = useTree.getState().nodeStates()
      const built = await generateLetter(states)
      generatedFrom.current = states
      setLetter(built)
      // Back to the rendered view, not a textarea: the participant has to be
      // able to click a citation before they can be said to have checked one.
      setEditedText(null)
    } catch {
      setGenerateFailed(true)
    } finally {
      setGenerating(false)
    }
  }, [])

  useEffect(() => {
    if (!material || generatedOnce.current) return
    if (state.phase !== 'generation' && state.phase !== 'verification') return
    generatedOnce.current = true
    void runGeneration('phase_enter')
  }, [material, state.phase, runGeneration])

  // --- linkage -------------------------------------------------------------
  /** Select an evidence chip and say what selected it.
   *
   * `via` is not decoration. Pressing the magnifier also selects the chip --
   * deliberately, so the linkage panels follow the thing being magnified --
   * and that selection used to be logged as `via: "click"`, identical to
   * clicking the card itself. Any count of "evidence cards the participant
   * opened" was then inflated by one for every magnifier press, and no field
   * in the log could separate the two.
   */
  const commitChip = useCallback((chipId: string, via: 'click' | 'linkage' | 'chip_magnifier') => {
    const target = snippets[chipId]
    if (!target) return
    logger.log(via === 'linkage' ? 'cite_click' : 'chip_click', {
      snippet_id: chipId,
      exhibit: target.exhibit,
      page: target.page,
      label: target.label,
      node_id: ownerOf(chipId)?.id,
      node_title: ownerOf(chipId)?.title,
      via,
    })
    logger.log('page_change', {
      exhibit: target.exhibit, page: target.page, via: 'linkage',
      reason: via === 'linkage' ? 'citation'
        : via === 'chip_magnifier' ? 'evidence chip magnifier'
        : 'evidence chip',
    })
    setCommittedChip(chipId)
    setPreviewChip(null)
    setExhibit(target.exhibit)
    setPage(target.page)
    setLightboxPage(target.page)

    const owner = ownerOf(chipId)
    if (owner) {
      paraRefs.current[owner.id]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      if (via === 'linkage') {
        subRefs.current[owner.id]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      }
    }
  }, [snippets, ownerOf])

  const focusSub = useCallback((subId: string) => {
    const sub = tree.args.flatMap((a) => a.subs).find((s) => s.id === subId)
    if (sub?.snippet_ids.length) commitChip(sub.snippet_ids[0], 'click')
  }, [tree.args, commitChip])

  /**
   * Open the magnifier on a NAMED snippet.
   *
   * The snippet id is a parameter rather than read from `committedChip`,
   * because every caller commits a focus and opens the magnifier in the same
   * breath -- and React has not applied that state by the time this runs. The
   * earlier version read the stale value and logged the PREVIOUSLY selected
   * exhibit while the dialog on screen showed the new one. The picture was
   * right and the data was wrong, which is the worse way round: it would have
   * recorded participants checking sources they never opened.
   */
  const openLightbox = useCallback((snippetId: string | null, atPage: number, via: string) => {
    const id = snippetId ?? committedChip
    if (!id) return
    const s = snippets[id]
    if (!s) return
    logger.log('lightbox_open', {
      snippet_id: id, exhibit: s.exhibit, page: atPage,
      cited_page: s.page, label: s.label, via,
    })
    closeDwell.current = startDwell('lightbox_close', {
      snippet_id: id, exhibit: s.exhibit, page: atPage,
    })
    setLightboxChip(id)
    setLightboxPage(atPage)
    setLightboxOpen(true)
    void usePractice.getState().clear('lightbox')
  }, [committedChip, snippets])

  const closeLightbox = useCallback(() => {
    closeDwell.current?.()
    closeDwell.current = null
    setLightboxOpen(false)
  }, [])

  // --- keyboard (C-12) -----------------------------------------------------
  const onKeyDown = (e: React.KeyboardEvent) => {
    if (lightboxOpen) return
    const flat = tree.args.flatMap((a) => a.subs).filter((s) => s.state !== 'removed')
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
      tree.setState(focusedSub, 'accepted', 'keyboard')
    }
    if (e.key.toLowerCase() === 'v' && committedChip) {
      e.preventDefault()
      openLightbox(committedChip, snippets[committedChip]?.page ?? 1, 'keyboard')
    }
  }

  // --- submit --------------------------------------------------------------
  /** Handing in is irreversible: the server refuses further log writes and the
   *  verification phase is over. It was one click on a button that sits beside
   *  Help in the top bar, with nothing between the click and the end of the
   *  measured task. */
  const [confirmSubmit, setConfirmSubmit] = useState(false)

  const onSubmit = async () => {
    setConfirmSubmit(false)
    const text = editedText ?? letter?.sentences.map((s) => s.text).join(' ') ?? ''
    logger.log('declare_done', { condition: 'c', char_count: text.length })
    // The declaration has to be in the log before the session locks, or the
    // moment they decided to stop is the one event that did not make it.
    await logger.flush()
    await submitFinal(text)
  }

  if (!material) return null

  const crumb = snippet ? (
    <>
      <span className="px-1.5 py-0.5 rounded bg-slate-100">
        {parentTitles[focusedSub ?? ''] ?? material.criterion ?? t('app.criterion')}
      </span>
      <span className="text-slate-300">{CRUMB_SEP}</span>
      <span className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 font-medium">
        {nodeTitles[focusedSub ?? ''] || t('crumb.unassigned')}
      </span>
      <span className="text-slate-300">{CRUMB_SEP}</span>
      <span className="mono px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 font-semibold">
        {t('ref.exPage', { ex: snippet.exhibit, i: snippet.page })}
      </span>
    </>
  ) : (
    <span className="text-slate-400">{t('crumb.nothing')}</span>
  )

  // Explicit per phase rather than a ternary chain ending in `verify`. That
  // default put "Review & revise - Submit when ready" above the practice
  // phase, and above setup and tutorial before those were routed elsewhere:
  // the heading told the participant which task they were doing, and it was
  // naming the wrong one.
  const PHASE_LABELS: Record<string, string> = {
    practice: 'phase.practice',
    organization: 'phase.organization',
    generation: 'phase.generation',
    verification: 'phase.verify',
  }
  const phaseLabel = t(PHASE_LABELS[state.phase] ?? 'phase.waiting')

  const lightboxExhibit = lightboxChip ? snippets[lightboxChip]?.exhibit : viewExhibit
  const lightboxPages =
    material.exhibits.find((e) => e.id === lightboxExhibit)?.pages ?? 1

  return (
    <div
      id="app"
      onKeyDown={onKeyDown}
      style={
        inPractice
          ? { gridTemplateRows: 'var(--h-topbar) var(--h-status) minmax(0,1fr)' }
          : undefined
      }
    >
      <TopBar
        condition="c"
        track={state.track}
        phaseLabel={phaseLabel}
        caseLabel={material.case_label}
        criterion={material.criterion}
        cfr={material.cfr}
        remainingMs={visibleRemainingMs(state)}
        canSubmit={state.can_submit}
        onHelp={() => {
          logger.log('panel_focus', { panel: 'topbar', target: 'help' })
          setHelpOpen((v) => !v)
        }}
        onSubmit={() => {
          logger.log('panel_focus', { panel: 'topbar', target: 'submit_intent' })
          setConfirmSubmit(true)
        }}
      />

      {inPractice && practice.loaded && (
        <PracticeGate
          required={practice.required}
          cleared={practice.cleared}
          complete={practice.complete}
        />
      )}

      <div id="main">
        <aside
          className="panel bg-white border-r border-slate-200"
          style={{ gridTemplateRows: 'auto auto auto minmax(0,1fr) auto auto' }}
        >
          <EvidenceViewer
            exhibits={material.exhibits}
            activeExhibit={viewExhibit}
            page={viewPage}
            zoom={zoom}
            linkage={showLinkage && snippet ? { snippet, preview: previewChip !== null } : undefined}
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
                <p className="text-[10px] font-bold text-slate-400 tracking-widest flex-shrink-0">
                  {t('crumb.label')}
                </p>
                <div className="flex items-center gap-1.5 text-[11px] text-slate-600 flex-nowrap overflow-hidden whitespace-nowrap min-w-0">
                  {crumb}
                </div>
              </div>
            }
            onOpenLightbox={() => openLightbox(effectiveChip, viewPage, 'bbox')}
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
          {snippet && (
            <RelationsPanel
              snippet={snippet}
              relations={material.relations}
              onMentionClick={(ex, pg) => {
                logger.log('doc_open', { exhibit: ex, from_exhibit: exhibit, via: 'relations' })
                logger.log('page_change', {
                  exhibit: ex, page: pg, via: 'linkage', reason: 'other mention',
                })
                setExhibit(ex)
                setPage(pg)
              }}
            />
          )}
        </aside>

        <TreePanel
          snippets={snippets}
          unusedSnippetIds={unusedSnippetIds}
          focusedSub={focusedSub}
          committedChip={committedChip}
          previewChip={previewChip}
          onFocusSub={focusSub}
          onChipHoverStart={(id) => {
            if (id === committedChip) return
            const s = snippets[id]
            if (!s) return
            // hover_start / hover_end are a LOOK; chip_click is a CHOICE. The
            // pair is what lets the analysis count evidence a participant
            // inspected but did not act on (C-05).
            logger.log('hover_start', {
              snippet_id: id, exhibit: s.exhibit, page: s.page, label: s.label,
            })
            hoverDwell.current = startDwell('hover_end', {
              snippet_id: id, exhibit: s.exhibit, page: s.page, label: s.label,
            })
            setPreviewChip(id)
          }}
          onChipHoverEnd={() => {
            hoverDwell.current?.()
            hoverDwell.current = null
            setPreviewChip(null)
          }}
          onChipClick={(id) => {
            commitChip(id, 'click')
            void usePractice.getState().clear('linkage')
          }}
          onChipZoom={(id) => {
            commitChip(id, 'chip_magnifier')
            openLightbox(id, snippets[id]?.page ?? 1, 'chip_magnifier')
          }}
          registerSubRef={(id, el) => {
            subRefs.current[id] = el
          }}
        />

        <LetterPanel
          sentences={letter?.sentences ?? []}
          criterion={material.criterion}
          editedText={editedText}
          focusedSub={focusedSub}
          argumentTitles={argumentTitles}
          staleNodeIds={staleNodeIds}
          generating={generating}
          onCiteClick={(id) => {
            // Locate and highlight only. The magnifier is a separate,
            // deliberate act -- clicking the box on the page, or the button on
            // the page corner. Opening it here made every citation click count
            // as a magnify, so "did they open the source" measured the
            // interface rather than the participant.
            commitChip(id, 'linkage')
            void usePractice.getState().clear('linkage')
          }}
          onRegenerate={() => void runGeneration('participant')}
          onEdit={setEditedText}
          registerParaRef={(sub, el) => {
            paraRefs.current[sub] = el
          }}
        />
      </div>

      {confirmSubmit && (
        <div className="fixed inset-0 z-[95] bg-slate-900/45 backdrop-blur-[2px] grid place-items-center">
          <div className="bg-white rounded-xl shadow-xl border border-slate-200 px-8 py-6 text-center max-w-[420px]">
            <p className="text-[14px] font-semibold text-slate-800 mb-1">
              {t('submit.confirmTitle')}
            </p>
            <p className="text-[12.5px] text-slate-500 mb-4">{t('submit.confirmBody')}</p>
            <div className="flex items-center justify-center gap-2">
              <button
                className="px-3 py-1.5 rounded-md border border-slate-200 text-[12.5px] font-semibold text-slate-600"
                onClick={() => setConfirmSubmit(false)}
              >
                {t('submit.confirmNo')}
              </button>
              <button
                className="px-3 py-1.5 rounded-md bg-slate-900 text-white text-[12.5px] font-semibold"
                onClick={() => void onSubmit()}
              >
                {t('submit.confirmYes')}
              </button>
            </div>
          </div>
        </div>
      )}

      {generateFailed && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[95] px-4 py-2 rounded-lg bg-rose-600 text-white text-[12.5px] shadow-lg">
          {t('letter.generateFailed')}
        </div>
      )}

      <Lightbox
        open={lightboxOpen}
        snippet={lightboxChip ? snippets[lightboxChip] ?? null : null}
        exhibitPages={lightboxPages}
        page={lightboxPage}
        zoom={lightboxZoom}
        crumb={crumb}
        onZoom={setLightboxZoom}
        onClose={closeLightbox}
        onPage={(p) => {
          logger.log('page_change', {
            exhibit: lightboxChip ? snippets[lightboxChip]?.exhibit : undefined,
            page: p, from_page: lightboxPage, via: 'click', surface: 'lightbox',
          })
          setLightboxPage(p)
        }}
        onScroll={(top) => logger.log('lightbox_scroll', { scroll_top: top })}
      />

      <HelpDrawer open={helpOpen} condition="c" onClose={() => setHelpOpen(false)} />
    </div>
  )
}
