/**
 * 3× magnifier (C-11). Mounted in condition C only.
 *
 * Restraint red line, deliberate and load-bearing: this dialog shows the
 * located passage and NOTHING ELSE. In particular it renders no neighbouring
 * candidate boxes -- the product frontend's BBoxLightbox takes a
 * `candidateBoxes` prop, and the study build would pass an empty array forever,
 * so the prop simply does not exist here. Highlighting "other passages that
 * might also fit" would be the interface making the judgement we are measuring
 * the participant on. Do not add it back because it looks helpful; it is the
 * experiment.
 *
 * Likewise there is no "is this enough support?" affordance, no confidence
 * shading, and no diff against the sentence being verified.
 *
 * Scrolling is reported (`onScroll`) because reading around a cited passage is
 * verification behaviour: someone who opened the magnifier and read the rest of
 * the page did something different from someone who opened and closed it.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { pageImageUrl } from '../../lib/pageImage'
import type { Snippet } from '../../lib/material'

const ZOOM_LEVELS = [1, 2, 3] as const
export type LightboxZoom = (typeof ZOOM_LEVELS)[number]

interface Props {
  open: boolean
  snippet: Snippet | null
  /** Page count of the exhibit the snippet belongs to. */
  exhibitPages: number
  /** Page currently shown. Its own value, not the snippet's: the participant
   *  may page away from the cited page to check the surrounding document, and
   *  whether they did is exactly the behaviour the study measures. */
  page: number
  zoom: LightboxZoom
  crumb: React.ReactNode
  onZoom: (z: LightboxZoom) => void
  onClose: () => void
  onPage: (page: number) => void
  onScroll: (scrollTop: number) => void
}

/** Scroll reports are throttled: a wheel gesture is dozens of events and the
 *  analysis needs the trajectory, not every pixel of it. */
const SCROLL_THROTTLE_MS = 300


/** One page of the exhibit, fetched with the participant's token. */
function LightboxPage({ exhibit, page }: { exhibit: string; page: number }) {
  const { t } = useTranslation()
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let live = true
    setUrl(null)
    setFailed(false)
    pageImageUrl(exhibit, page)
      .then((u) => live && setUrl(u))
      .catch(() => live && setFailed(true))
    return () => {
      live = false
    }
  }, [exhibit, page])

  if (url) return <img src={url} alt="" className="block w-full max-w-full select-none" draggable={false} />
  return (
    <div className="w-full grid place-items-center text-[12px] text-slate-400"
         style={{ aspectRatio: '1 / 1.29' }}>
      {failed ? t('evidence.pageUnavailable') : ''}
    </div>
  )
}

export function Lightbox({
  open, snippet, exhibitPages, page, zoom, crumb, onZoom, onClose, onPage, onScroll,
}: Props) {
  const { t } = useTranslation()
  const lastScroll = useRef(0)

  useEffect(() => {
    if (!open || !snippet) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft') onPage(Math.max(1, page - 1))
      if (e.key === 'ArrowRight') onPage(Math.min(exhibitPages, page + 1))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, snippet, page, exhibitPages, onClose, onPage])

  if (!open || !snippet) return null

  // The cited passage lives on exactly one page. Paging elsewhere shows the
  // document as it is -- with nothing highlighted, because there is nothing
  // there to point at.
  const onCitedPage = page === snippet.page

  return (
    <div
      id="lb"
      className="open"
      role="dialog"
      aria-modal="true"
      aria-label={t('lightbox.title')}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div id="lbCard">
        <div className="px-5 py-3 border-b border-slate-200 flex items-center gap-3 bg-white">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 text-[11.5px] text-slate-600 flex-wrap">{crumb}</div>
          </div>
          <div className="ml-auto flex items-center gap-2 flex-shrink-0">
            <div className="flex items-center rounded-lg border border-slate-200 overflow-hidden">
              {ZOOM_LEVELS.map((z, i) => (
                <span key={z} className="contents">
                  {i > 0 && <span className="w-px h-4 bg-slate-200" />}
                  <button
                    onClick={() => onZoom(z)}
                    className={
                      z === zoom
                        ? 'px-2.5 py-1.5 text-[12px] font-semibold bg-slate-900 text-white'
                        : 'px-2.5 py-1.5 text-[12px] text-slate-600 hover:bg-slate-50'
                    }
                  >
                    {z * 100}%
                  </button>
                </span>
              ))}
            </div>
            <button
              onClick={onClose}
              className="w-8 h-8 rounded-lg border border-slate-200 text-slate-500 flex items-center justify-center hover:bg-slate-50"
              aria-label={t('lightbox.close')}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path d="M6 6l12 12M18 6L6 18" />
              </svg>
            </button>
          </div>
        </div>

        <div
          className="scroll bg-slate-200 p-8"
          onScroll={(e) => {
            const now = performance.now()
            if (now - lastScroll.current < SCROLL_THROTTLE_MS) return
            lastScroll.current = now
            onScroll(Math.round(e.currentTarget.scrollTop))
          }}
        >
          {/* The page as it is. On the cited page the passage is boxed; on any
              other page nothing is -- turning away from the citation has to
              show the document unmarked, or "I checked the source" stops
              meaning the participant read anything (C-11). */}
          <div id="lbPage" className="bg-white mx-auto shadow-xl relative"
               style={{ width: 300 * zoom }}>
            <div className="absolute top-2 left-3 z-10 text-[12px] text-slate-400 bg-white/80 px-1.5 rounded">
              {t('ref.page', { i: page })}
            </div>
            <LightboxPage exhibit={snippet.exhibit} page={page} />
            {onCitedPage && (
              <div
                className="absolute pointer-events-none rounded-sm border-[3px] border-blue-500 bg-blue-500/10"
                style={{
                  // 红线 #8: the bundle's 1000x1000 space, so /10 is a percentage
                  // of the page and the box holds at every zoom level.
                  left: `${snippet.bbox[0] / 10}%`,
                  top: `${snippet.bbox[1] / 10}%`,
                  width: `${(snippet.bbox[2] - snippet.bbox[0]) / 10}%`,
                  height: `${(snippet.bbox[3] - snippet.bbox[1]) / 10}%`,
                }}
              >
                <span className="absolute -top-3.5 left-2 px-2 py-0.5 rounded bg-blue-600 text-white text-[10.5px] font-bold mono whitespace-nowrap">
                  {t('ref.exPageTag', { ex: snippet.exhibit, i: snippet.page })}
                </span>
              </div>
            )}
          </div>
        </div>

        <div className="px-5 py-3 border-t border-slate-200 flex items-center gap-3 bg-white">
          <button
            className="px-3 py-1.5 rounded-lg border border-slate-200 text-[12.5px] text-slate-600 hover:bg-slate-50"
            disabled={page <= 1}
            onClick={() => onPage(page - 1)}
          >
            {t('pager.prev')}
          </button>
          <span className="mono text-[12.5px] text-slate-500">
            {t('lightbox.nav', { ex: snippet.exhibit, i: page, n: exhibitPages })}
          </span>
          <button
            className="px-3 py-1.5 rounded-lg border border-slate-200 text-[12.5px] text-slate-600 hover:bg-slate-50"
            disabled={page >= exhibitPages}
            onClick={() => onPage(page + 1)}
          >
            {t('pager.next')}
          </button>
          <span className="ml-auto text-[11.5px] text-slate-400">{t('lightbox.hint')}</span>
        </div>
      </div>
    </div>
  )
}
