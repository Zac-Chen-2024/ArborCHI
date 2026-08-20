/**
 * Condition B -- DraftDesk. Layout mirrors mockups/baseline-shell-b-v3.html.
 *
 * Same three-column shell, same EvidenceViewer, same top-bar rhythm. The
 * differences are exactly the ones the design predicts and no others:
 *
 *   - `linkage` is not passed, so there is no bbox highlight and no jump-to.
 *     Manual navigation (exhibit chips, pager) is the only route to a page.
 *   - Citations in the draft are plain text. They are not clickable, because
 *     there is nothing to click through to (B-02).
 *   - No clock, in any phase (B-04).
 *
 * The chat's first exchange is injected by the server (BE-09); the client
 * never sends the bootstrap prompt itself, it only renders what comes back.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { EvidenceViewer } from '../../components/shared/EvidenceViewer'
import { TopBar } from '../../components/shared/TopBar'
import { DRAFT_FIXTURE, PAGE_BODY_FIXTURE } from '../../data/fixtures'
import { fetchMaterial, type Material } from '../../lib/material'
import type { StudyState } from '../../lib/api'
import { logger } from '../../lib/logger'
import { usePractice } from '../../lib/practice'
import { HelpDrawer } from '../common/HelpDrawer'
import { PracticeGate } from '../common/PracticeGate'
import { ChatPanel } from './ChatPanel'
import { DraftEditor } from './DraftEditor'
import './b.css'

interface Props {
  state: StudyState
}

export function ConditionB({ state }: Props) {
  const { t } = useTranslation()
  const practice = usePractice()
  const inPractice = state.phase === 'practice'

  useEffect(() => {
    if (inPractice) void usePractice.getState().refresh()
  }, [inPractice])

  const [material, setMaterial] = useState<Material | null>(null)
  const [exhibit, setExhibit] = useState('')

  useEffect(() => {
    // Refetched on the practice boundary: practice runs on a different bundle.
    void (async () => {
      const m = await fetchMaterial()
      setMaterial(m)
      if (m.exhibits[0]) setExhibit(m.exhibits[0].id)
    })()
  }, [inPractice])
  const [page, setPage] = useState(2)
  const [zoom, setZoom] = useState(1)
  const [draft, setDraft] = useState(DRAFT_FIXTURE)
  const [helpOpen, setHelpOpen] = useState(false)

  const exhibits = material?.exhibits ?? []
  const current = exhibits.find((e) => e.id === exhibit) ?? exhibits[0]

  if (!material) return null

  return (
    <div
      id="app"
      style={
        inPractice
          ? { gridTemplateRows: 'var(--h-topbar) var(--h-status) minmax(0,1fr)' }
          : undefined
      }
    >
      <TopBar
        condition="b"
        track={state.track}
        phaseLabel={t('phase.work')}
        canSubmit={state.can_submit}
        // B never shows a clock, in any phase. This is not a conditional --
        // the value is null at the call site (B-04).
        remainingMs={null}
        onHelp={() => {
          logger.log('panel_focus', { panel: 'topbar', target: 'help' })
          setHelpOpen((v) => !v)
        }}
        onSubmit={() => logger.log('declare_done', { condition: 'b' })}
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
          style={{ gridTemplateRows: 'auto auto auto minmax(0,1fr) auto' }}
        >
          <EvidenceViewer
            exhibits={exhibits}
            docTitle={current?.title ?? ''}
            docSubtitle={t('doc.page', { i: page })}
            bodyText={PAGE_BODY_FIXTURE}
            activeExhibit={exhibit}
            page={page}
            zoom={zoom}
            // No `linkage` prop: same component, no highlight, no jump-to.
            title={t('evidence.titleB')}
            contextStrip={
              <div className="ctxstrip">
                <p className="text-[10px] font-bold text-slate-400 tracking-widest flex-shrink-0">{t('doc.current')}</p>
                <span className="mono text-[11px] px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 font-semibold flex-shrink-0">
                  {current?.id}
                </span>
                <span className="text-[11px] text-slate-600 truncate">{current?.title}</span>
              </div>
            }
            onExhibitClick={(id) => {
              logger.log('doc_open', { exhibit: id, from_exhibit: exhibit, via: 'chip' })
              logger.log('page_change', { exhibit: id, page: 1, via: 'click', reason: 'exhibit chip' })
              setExhibit(id)
              setPage(1)
            }}
            onPageChange={(p, via) => {
              logger.log('page_change', { exhibit, page: p, from_page: page, via })
              setPage(p)
              // B's only route to the evidence is its own hands (B-03), so the
              // gate is having used it.
              void usePractice.getState().clear('manual_page')
            }}
            onZoom={(z) => {
              logger.log('zoom', { panel: 'evidence', from: zoom, to: z })
              setZoom(z)
            }}
          />
        </aside>

        <ChatPanel
          onCopyToDraft={(text) => {
            logger.log('copy_to_draft', {
              char_count: text.length,
              preview: text.slice(0, 200),
            })
            setDraft((d) => `${d}\n\n${text}`)
          }}
        />

        <DraftEditor value={draft} onChange={setDraft} />
      </div>

      <HelpDrawer open={helpOpen} condition="b" onClose={() => setHelpOpen(false)} />
    </div>
  )
}
