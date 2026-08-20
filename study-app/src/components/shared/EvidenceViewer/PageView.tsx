/**
 * The scrolling page area. M0 renders the mockup's placeholder page; at M2
 * this becomes the real OCR page, and the bbox rectangle is positioned from
 * the bundle's normalised coordinates.
 *
 * bbox convention (红线 #8): the bundle stores coordinates in a 1000×1000
 * normalised space -- divide by 1000 to get a fraction of the page, then
 * multiply by the rendered page box. Never store or read pixels; the same
 * snippet has to land correctly at every zoom level and every render width.
 * This mirrors DocumentViewer.tsx in the product frontend, which is where the
 * arithmetic is being carried over from.
 */
import { useTranslation } from 'react-i18next'

import type { Linkage } from './index'

interface Props {
  page: number
  zoom: number
  linkage?: Linkage
  /** Document header, from the material rather than hard-coded. Both
   *  conditions print the same header for the same page -- the difference
   *  between them is the highlight, not the document. */
  docTitle: string
  docSubtitle: string
  /** Page body shown when there is no linkage (condition B, or a page the
   *  focused snippet does not live on). The same passage is present either
   *  way; only the pointing differs (B-03). */
  bodyText: string
  onOpenLightbox?: () => void
}

/** Placeholder text lines, matching the mockup's bar widths. */
const BARS_ABOVE = [88, 76]
const BARS_BELOW = [92, 80, 86, 70, 84]
const NEXT_PAGE_BARS = [84, 90, 72]

export function PageView({ page, zoom, linkage, docTitle, docSubtitle, bodyText, onOpenLightbox }: Props) {
  const { t } = useTranslation()
  const snippet = linkage?.snippet

  return (
    <div className="scroll bg-slate-50 p-3">
      <div className="paper relative" style={{ zoom }}>
        {onOpenLightbox && (
          <button
            onClick={onOpenLightbox}
            className="absolute top-2 right-2 w-6 h-6 rounded border border-slate-200 bg-white text-slate-400 flex items-center justify-center hover:text-blue-600 hover:border-blue-300"
            aria-label={t('lightbox.open')}
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-3.5-3.5M11 8v6M8 11h6" />
            </svg>
          </button>
        )}
        <div className="text-[10px] text-slate-300 mb-2">{t('ref.page', { i: page })}</div>
        <p className="text-[12px] font-bold text-slate-600 text-center">{docTitle}</p>
        <p className="text-[10px] text-slate-400 text-center mb-3.5">{docSubtitle}</p>
        {BARS_ABOVE.map((w, i) => (
          <div key={i} className="pagebar" style={{ width: `${w}%` }} />
        ))}

        {snippet ? (
          // Condition C only: the located passage. `is-preview` distinguishes a
          // hover look-ahead from a committed click (C-05).
          <div
            className={`rounded px-3 py-2.5 my-2.5 border-2 border-blue-500 bg-blue-50/70 ${
              linkage?.preview ? 'border-dashed' : ''
            }`}
          >
            <p className="text-[12px] text-slate-800 leading-relaxed">{snippet.text}</p>
          </div>
        ) : (
          // Condition B: the same passage is on the page as ordinary text --
          // equally available, just not pointed at.
          <p className="text-[12px] text-slate-800 leading-relaxed my-2.5">{bodyText}</p>
        )}

        {BARS_BELOW.map((w, i) => (
          <div
            key={i}
            className="pagebar"
            style={{ width: `${w}%`, marginBottom: i === BARS_BELOW.length - 1 ? 0 : undefined }}
          />
        ))}
      </div>

      {/* Continuous paging: the next page sits below, dimmed, as in the mockup.
          It reports nothing. An earlier version fired page_change{via:"scroll"}
          on mouseenter as a stand-in for real scroll detection -- that would
          have written a navigation the participant never made into the event
          log. Real scroll tracking (IntersectionObserver over the page nodes)
          lands with the OCR pages at M2; until then this is presentation only. */}
      <div className="paper mt-2.5 opacity-40" style={{ zoom }}>
        <div className="text-[10px] text-slate-300 mb-2">{t('ref.page', { i: page + 1 })}</div>
        {NEXT_PAGE_BARS.map((w, i) => (
          <div
            key={i}
            className="pagebar"
            style={{ width: `${w}%`, marginBottom: i === NEXT_PAGE_BARS.length - 1 ? 0 : undefined }}
          />
        ))}
      </div>
    </div>
  )
}
