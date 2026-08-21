/**
 * The scrolling page area: the exhibit page as it actually looks, with the
 * cited passage boxed on it.
 *
 * This drew the mockup's grey placeholder bars until the real material landed.
 * That was right for a wireframe and wrong the moment a participant is asked to
 * check a sentence against the page it cites: three of the five planted error
 * kinds are findable only by reading the exhibit, `source_opened` and the
 * magnifier dwell are dependent variables, and the bbox exists to put a
 * highlight somewhere. None of that means anything over grey bars.
 *
 * bbox convention (红线 #8): the bundle stores a 1000×1000 normalised space, so
 * a coordinate divided by 10 is a percentage of the rendered page. Positioned in
 * percentages rather than pixels, the box lands correctly at every zoom level
 * and every render width, and the image's own size never has to be known here.
 *
 * Parity (§D3, B-03): the PAGE is identical in both conditions. `linkage` adds
 * the box and nothing else -- same document, same passage on it, different
 * pointing.
 */
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { pageImageUrl } from '../../../lib/pageImage'
import type { Linkage } from './index'

interface Props {
  exhibit: string
  page: number
  /** Pages in this exhibit, so the trailing next-page preview knows to stop. */
  pageCount: number
  zoom: number
  linkage?: Linkage
  /** `via` names the affordance: the corner button, or the highlighted
   *  passage itself. They are different acts and the log has to tell
   *  them apart. */
  onOpenLightbox?: (via: 'page_button' | 'bbox') => void
}

/** One rendered page, or a reason it is not there. */
function Page({ exhibit, page, dim }: { exhibit: string; page: number; dim?: boolean }) {
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

  return (
    <div className={`relative bg-white ${dim ? 'opacity-40' : ''}`}>
      <div className="absolute top-1.5 left-2 z-10 text-[10px] text-slate-400 bg-white/80 px-1 rounded">
        {t('ref.page', { i: page })}
      </div>
      {url ? (
        <img
          src={url}
          alt=""
          className="block w-full max-w-full select-none"
          draggable={false}
        />
      ) : (
        // A fixed aspect box so the page does not jump when the image lands.
        // Failure says so rather than showing an empty frame: a participant
        // staring at a blank exhibit should be able to tell the researcher
        // something is wrong, not conclude the document is blank.
        <div className="w-full grid place-items-center text-[11px] text-slate-400"
             style={{ aspectRatio: '1 / 1.29' }}>
          {failed ? t('evidence.pageUnavailable') : ''}
        </div>
      )}
    </div>
  )
}

export function PageView({ exhibit, page, pageCount, zoom, linkage, onOpenLightbox }: Props) {
  const { t } = useTranslation()
  const boxRef = useRef<HTMLDivElement | null>(null)
  const snippet = linkage?.snippet
  // Only box the passage when it is on the page being looked at. Turning to
  // another page must not leave a rectangle behind on unrelated text (C-11).
  const box =
    snippet && snippet.exhibit === exhibit && snippet.page === page ? snippet.bbox : null

  // Bring the located passage to the middle of the panel rather than leaving it
  // wherever it happens to fall. A citation on page 9 of a twelve-page exhibit
  // otherwise lands off-screen, and "follow the citation" quietly becomes
  // "follow the citation, then hunt".
  useEffect(() => {
    if (!box || !boxRef.current) return
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    boxRef.current.scrollIntoView({
      block: 'center',
      inline: 'nearest',
      behavior: reduce ? 'auto' : 'smooth',
    })
  }, [exhibit, page, snippet?.snippet_id, box])

  return (
    <div className="scroll bg-slate-50 p-3">
      <div className="paper relative overflow-hidden" style={{ zoom, padding: 0 }}>
        {onOpenLightbox && (
          <button
            onClick={() => onOpenLightbox('page_button')}
            className="absolute top-2 right-2 z-20 w-6 h-6 rounded border border-slate-200 bg-white text-slate-400 flex items-center justify-center hover:text-blue-600 hover:border-blue-300"
            aria-label={t('lightbox.open')}
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-3.5-3.5M11 8v6M8 11h6" />
            </svg>
          </button>
        )}

        <div className="relative">
          <Page exhibit={exhibit} page={page} />
          {box && (
            // The box itself is the way into the magnifier: hovering it says so,
            // and it takes a click. A hover preview stays inert -- the pointer
            // is only passing over an evidence card, and arming a control under
            // the cursor there would open the magnifier by accident.
            <div
              ref={boxRef}
              role={onOpenLightbox && !linkage?.preview ? 'button' : undefined}
              tabIndex={onOpenLightbox && !linkage?.preview ? 0 : undefined}
              aria-label={onOpenLightbox ? t('lightbox.open') : undefined}
              onClick={onOpenLightbox && !linkage?.preview ? () => onOpenLightbox('bbox') : undefined}
              onKeyDown={
                onOpenLightbox && !linkage?.preview
                  ? (e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onOpenLightbox('bbox')
                      }
                    }
                  : undefined
              }
              className={`bbox absolute rounded-sm border-2 border-blue-500 bg-blue-500/10 ${
                linkage?.preview
                  ? 'border-dashed pointer-events-none'
                  : onOpenLightbox
                    ? 'is-zoomable'
                    : 'pointer-events-none'
              }`}
              style={{
                left: `${box[0] / 10}%`,
                top: `${box[1] / 10}%`,
                width: `${(box[2] - box[0]) / 10}%`,
                height: `${(box[3] - box[1]) / 10}%`,
              }}
            >
              {onOpenLightbox && !linkage?.preview && (
                <span className="bbox-zoom" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                    <circle cx="11" cy="11" r="7" />
                    <path d="M20 20l-3.5-3.5M11 8v6M8 11h6" />
                  </svg>
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Continuous paging: the next page sits below, dimmed, as in the mockup.
          It reports nothing. An earlier version fired page_change{via:"scroll"}
          on mouseenter as a stand-in for real scroll detection -- that would
          have written a navigation the participant never made into the event
          log. */}
      {page < pageCount && (
        <div className="paper mt-2.5 overflow-hidden" style={{ zoom, padding: 0 }}>
          <Page exhibit={exhibit} page={page + 1} dim />
        </div>
      )}
    </div>
  )
}
