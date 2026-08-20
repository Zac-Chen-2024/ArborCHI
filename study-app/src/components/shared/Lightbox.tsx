/**
 * 3× magnifier (C-11). Mounted in condition C only.
 *
 * Restraint red line, deliberate and load-bearing: this dialog shows the
 * located passage and NOTHING ELSE. In particular it renders no neighbouring
 * candidate boxes -- the product frontend's BBoxLightbox takes a
 * `candidateBoxes` prop, and the study build passes an empty array forever.
 * Highlighting "other passages that might also fit" would be the interface
 * making the judgement we are measuring the participant on. Do not add it back
 * because it looks helpful; it is the experiment.
 *
 * Likewise there is no "is this enough support?" affordance, no confidence
 * shading, and no diff against the sentence being verified.
 */
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import type { Snippet } from '../../data/fixtures'

const ZOOM_LEVELS = [1, 2, 3] as const
export type LightboxZoom = (typeof ZOOM_LEVELS)[number]

interface Props {
  open: boolean
  snippet: Snippet | null
  zoom: LightboxZoom
  crumb: React.ReactNode
  onZoom: (z: LightboxZoom) => void
  onClose: () => void
  onPage: (page: number) => void
}

const LINES_ABOVE = [90, 82, 88]
const LINES_BELOW = [94, 78, 86, 91, 72, 88, 80]

export function Lightbox({ open, snippet, zoom, crumb, onZoom, onClose, onPage }: Props) {
  const { t } = useTranslation()

  useEffect(() => {
    if (!open || !snippet) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft') onPage(Math.max(1, snippet.page - 1))
      if (e.key === 'ArrowRight') onPage(Math.min(snippet.pages, snippet.page + 1))
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, snippet, onClose, onPage])

  if (!open || !snippet) return null

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

        <div className="scroll bg-slate-200 p-8">
          <div id="lbPage" className="bg-white mx-auto shadow-xl p-10" style={{ width: 300 * zoom }}>
            <div className="text-[12px] text-slate-300 mb-4">{t('ref.page', { i: snippet.page })}</div>
            <p className="text-[16px] font-bold text-slate-700 text-center">{snippet.docTitle}</p>
            <p className="text-[12px] text-slate-400 text-center mb-7">{snippet.docSubtitle}</p>
            {LINES_ABOVE.map((w, i) => (
              <div key={i} className="lbline" style={{ width: `${w}%` }} />
            ))}
            <div className="border-[3px] border-dashed border-blue-500 bg-blue-50/70 rounded-lg px-5 py-4 my-5 relative">
              <span className="absolute -top-3 left-4 px-2 py-0.5 rounded bg-blue-600 text-white text-[10.5px] font-bold mono">
                {t('ref.exPageTag', { ex: snippet.ex, i: snippet.page })}
              </span>
              <p className="text-[15px] text-slate-900 leading-[1.75]">{snippet.text}</p>
            </div>
            {LINES_BELOW.map((w, i) => (
              <div
                key={i}
                className="lbline"
                style={{ width: `${w}%`, marginBottom: i === LINES_BELOW.length - 1 ? 0 : undefined }}
              />
            ))}
          </div>
        </div>

        <div className="px-5 py-3 border-t border-slate-200 flex items-center gap-3 bg-white">
          <button
            className="px-3 py-1.5 rounded-lg border border-slate-200 text-[12.5px] text-slate-600 hover:bg-slate-50"
            disabled={snippet.page <= 1}
            onClick={() => onPage(snippet.page - 1)}
          >
            {t('pager.prev')}
          </button>
          <span className="mono text-[12.5px] text-slate-500">
            {t('lightbox.nav', { ex: snippet.ex, i: snippet.page, n: snippet.pages })}
          </span>
          <button
            className="px-3 py-1.5 rounded-lg border border-slate-200 text-[12.5px] text-slate-600 hover:bg-slate-50"
            disabled={snippet.page >= snippet.pages}
            onClick={() => onPage(snippet.page + 1)}
          >
            {t('pager.next')}
          </button>
          <span className="ml-auto text-[11.5px] text-slate-400">{t('lightbox.hint')}</span>
        </div>
      </div>
    </div>
  )
}
