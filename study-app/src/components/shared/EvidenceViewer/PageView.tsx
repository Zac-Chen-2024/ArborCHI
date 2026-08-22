/**
 * The exhibit, as one continuously scrolling document.
 *
 * Every page is stacked in one scroller rather than shown one at a time.
 * Reading a filing means running your eye down it and back up; a Prev / Next
 * pair turns that into a decision per page, and those decisions land in the log
 * as navigation the participant did not really make. A jump control remains for
 * going somewhere specific in a twelve-page exhibit.
 *
 * Which page is being read is therefore *observed* rather than commanded: the
 * page occupying most of the viewport is the current one, reported with
 * `via: "scroll"`. Moves the software makes on the participant's behalf --
 * following a citation -- are suppressed, or every linkage would also look like
 * a scroll (C-08).
 *
 * ## Two magnifications, and why they differ
 *
 * Hovering the located passage enlarges **that region only**, in place. It is a
 * reading aid: the passage is small on a 300px-wide page, and this makes it
 * legible without leaving the page or opening anything.
 *
 * The full magnifier dialog opens only from the button on the box. Opening it
 * is a measured act -- `lightbox_open`, its dwell, its scrolling -- so it takes
 * a deliberate press. Anything that opened it as a side effect of pointing at
 * something would record the interface's behaviour as the participant's.
 *
 * bbox convention (红线 #8): the bundle stores a 1000×1000 normalised space, so
 * a coordinate divided by 10 is a percentage of the page. Positioned in
 * percentages, the box holds at every zoom and every render width.
 *
 * Parity (§D3, B-03): the PAGES are identical in both conditions. `linkage`
 * adds the box, the loupe and the magnifier button; without it the same
 * document scrolls with nothing pointed at.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { pageImage, type PageImage } from '../../../lib/pageImage'
import { HoverLoupe } from './HoverLoupe'
import type { Linkage } from './index'

interface Props {
  exhibit: string
  /** The page to bring into view when it changes from outside -- a jump from
   *  the pager, or a citation. Scrolling never sets this; it reports instead. */
  page: number
  pageCount: number
  /** Height/width of each page, so space is reserved before the image lands. */
  pageAspects?: number[]
  zoom: number
  linkage?: Linkage
  /** Reading position, observed from scrolling. */
  onPageInView?: (page: number) => void
  onOpenLightbox?: () => void
}

/** Page shape assumed while nothing is known -- close to A4 and Letter. */
const FALLBACK_ASPECT = 1.3

/** One page: reserves its space immediately, loads its image when near. */
function Page({
  exhibit,
  page,
  aspect,
  onLoaded,
  children,
}: {
  exhibit: string
  page: number
  aspect: number
  onLoaded?: (img: PageImage) => void
  children?: React.ReactNode
}) {
  const { t } = useTranslation()
  const ref = useRef<HTMLDivElement | null>(null)
  const [img, setImg] = useState<PageImage | null>(null)
  const [failed, setFailed] = useState(false)
  const [near, setNear] = useState(false)

  // Only fetch what is about to be looked at. A twelve-page exhibit is twelve
  // images, and loading all of them the moment it opens would put a stall at
  // the front of every navigation.
  useEffect(() => {
    const el = ref.current
    if (!el || near) return
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => e.isIntersecting && setNear(true)),
      { rootMargin: '600px 0px' },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [near])

  useEffect(() => {
    if (!near) return
    let live = true
    setFailed(false)
    pageImage(exhibit, page)
      .then((p) => {
        if (!live) return
        setImg(p)
        onLoaded?.(p)
      })
      .catch(() => live && setFailed(true))
    return () => {
      live = false
    }
  }, [near, exhibit, page, onLoaded])

  return (
    <div
      ref={ref}
      data-page={page}
      className="paper relative overflow-hidden"
      style={{ padding: 0, aspectRatio: `1 / ${aspect}` }}
    >
      <div className="absolute top-1.5 left-2 z-10 text-[10px] text-slate-400 bg-white/85 px-1 rounded">
        {t('ref.page', { i: page })}
      </div>
      {img ? (
        <img src={img.url} alt="" className="block w-full max-w-full select-none" draggable={false} />
      ) : (
        <div className="w-full h-full grid place-items-center text-[11px] text-slate-400">
          {failed ? t('evidence.pageUnavailable') : ''}
        </div>
      )}
      {children}
    </div>
  )
}

export function PageView({
  exhibit,
  page,
  pageCount,
  pageAspects,
  zoom,
  linkage,
  onPageInView,
  onOpenLightbox,
}: Props) {
  const { t } = useTranslation()
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const boxRef = useRef<HTMLDivElement | null>(null)
  // True while this component is scrolling itself. Without it, following a
  // citation also reports a scroll, and the log stops telling a move the
  // participant made from one made for them.
  const programmatic = useRef(false)
  /** Last page the observer reported, so an outside jump can tell whether it
   *  needs to move at all -- and so reporting cannot re-trigger scrolling. */
  const inView = useRef(0)
  const [loupeFrom, setLoupeFrom] = useState<DOMRect | null>(null)
  const [citedImg, setCitedImg] = useState<PageImage | null>(null)

  const snippet = linkage?.snippet
  const citedPage = snippet && snippet.exhibit === exhibit ? snippet.page : null
  const box = snippet && citedPage !== null ? snippet.bbox : null
  const interactive = !!box && !linkage?.preview

  const aspectOf = (n: number) => pageAspects?.[n - 1] ?? FALLBACK_ASPECT

  // Bring the located passage to the middle of the panel. A citation on page 9
  // of a twelve-page exhibit otherwise lands wherever the scroller happens to
  // be, and "follow the citation" quietly becomes "follow it, then hunt".
  useEffect(() => {
    if (!box || !boxRef.current) return
    programmatic.current = true
    inView.current = citedPage ?? inView.current
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    boxRef.current.scrollIntoView({
      block: 'center',
      inline: 'nearest',
      behavior: reduce ? 'auto' : 'smooth',
    })
    const id = window.setTimeout(
      () => {
        programmatic.current = false
      },
      reduce ? 80 : 900,
    )
    return () => window.clearTimeout(id)
  }, [exhibit, snippet?.snippet_id, box, citedPage])

  // Which page is being read, observed rather than commanded.
  useEffect(() => {
    const root = scrollRef.current
    if (!root || !onPageInView) return
    const visible = new Map<number, number>()
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          visible.set(Number((e.target as HTMLElement).dataset.page), e.intersectionRatio)
        })
        if (programmatic.current) return
        let best = 0
        let bestRatio = 0
        visible.forEach((ratio, n) => {
          if (ratio > bestRatio) {
            bestRatio = ratio
            best = n
          }
        })
        if (best && bestRatio > 0.5 && best !== inView.current) {
          inView.current = best
          onPageInView(best)
        }
      },
      { root, threshold: [0, 0.25, 0.5, 0.75, 1] },
    )
    root.querySelectorAll('[data-page]').forEach((el) => io.observe(el))
    return () => io.disconnect()
  }, [exhibit, pageCount, onPageInView])

  // A jump from the pager, or a citation landing on a page with no box on it.
  // Skipped when the located passage is on that page: the box's own centring is
  // more precise and would otherwise fight this.
  useEffect(() => {
    const root = scrollRef.current
    if (!root || page === inView.current) return
    if (box && citedPage === page) return
    const el = root.querySelector(`[data-page="${page}"]`)
    if (!el) return
    programmatic.current = true
    inView.current = page
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    el.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' })
    const id = window.setTimeout(
      () => {
        programmatic.current = false
      },
      reduce ? 80 : 900,
    )
    return () => window.clearTimeout(id)
  }, [page, exhibit, box, citedPage])

  const onCitedLoaded = useCallback((img: PageImage) => setCitedImg(img), [])

  useEffect(() => {
    setLoupeFrom(null)
    setCitedImg(null)
  }, [exhibit, snippet?.snippet_id])

  return (
    <div ref={scrollRef} className="scroll bg-slate-50 p-3 flex flex-col gap-2.5">
      {Array.from({ length: pageCount }, (_, i) => i + 1).map((n) => (
        <div key={n} style={{ zoom }}>
          <Page
            exhibit={exhibit}
            page={n}
            aspect={aspectOf(n)}
            onLoaded={n === citedPage ? onCitedLoaded : undefined}
          >
            {box && n === citedPage && (
              <>
                <div
                  ref={boxRef}
                  onMouseEnter={(e) =>
                    interactive && setLoupeFrom(e.currentTarget.getBoundingClientRect())
                  }
                  onMouseLeave={() => setLoupeFrom(null)}
                  className={`bbox absolute rounded-sm border-2 border-blue-500 bg-blue-500/10 ${
                    linkage?.preview ? 'border-dashed pointer-events-none' : 'is-live'
                  }`}
                  style={{
                    left: `${box[0] / 10}%`,
                    top: `${box[1] / 10}%`,
                    width: `${(box[2] - box[0]) / 10}%`,
                    height: `${(box[3] - box[1]) / 10}%`,
                  }}
                >
                  {interactive && onOpenLightbox && (
                    <button
                      type="button"
                      className="bbox-zoom"
                      aria-label={t('lightbox.open')}
                      onClick={(e) => {
                        e.stopPropagation()
                        onOpenLightbox()
                      }}
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                        <circle cx="11" cy="11" r="7" />
                        <path d="M20 20l-3.5-3.5M11 8v6M8 11h6" />
                      </svg>
                    </button>
                  )}
                </div>

              </>
            )}
          </Page>
        </div>
      ))}

      {loupeFrom && citedImg && box && (
        <HoverLoupe page={citedImg} bbox={box} origin={loupeFrom} />
      )}
    </div>
  )
}
