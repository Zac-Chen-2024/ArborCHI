/**
 * Pager, 48px: where you are in the exhibit, a jump control, and zoom (FS-05).
 *
 * No Prev / Next. The exhibit scrolls as one document, so stepping a page at a
 * time is not how anyone reads it -- and every step would land in the log as
 * navigation, filling `page_change` with presses that stand in for scrolling.
 * What remains is the position (observed from the scroll, not commanded) and a
 * way to go somewhere specific in a twelve-page exhibit.
 *
 * A jump made here reports `via: "click"`; the same move triggered by a
 * citation or an evidence card reports `via: "linkage"`, and scrolling reports
 * `via: "scroll"`. That is how the analysis separates a participant's own
 * navigation from the system's (C-08).
 */
import { useTranslation } from 'react-i18next'

import { ZOOM_IN, ZOOM_OUT } from '../../../lib/glyphs'

const ZOOMS = [0.75, 1, 1.25, 1.5, 2]

interface Props {
  exhibit: string
  page: number
  pages: number
  zoom: number
  onPage: (page: number) => void
  onZoom: (zoom: number) => void
}

export function PagerBar({ exhibit, page, pages, zoom, onPage, onZoom }: Props) {
  const { t } = useTranslation()
  const step = (delta: number) => {
    const i = ZOOMS.indexOf(zoom)
    const next = ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, (i === -1 ? 1 : i) + delta))]
    onZoom(next)
  }

  return (
    <div className="pager">
      <span className="mono text-[11px] text-slate-500 truncate">
        {t('pager.pos', { ex: exhibit, i: page, n: pages })}
      </span>

      <label className="ml-auto flex items-center gap-1.5 flex-shrink-0">
        <span className="text-[10.5px] text-slate-400">{t('pager.jump')}</span>
        <select
          className="pgsel mono"
          value={page}
          onChange={(e) => onPage(Number(e.target.value))}
          aria-label={t('pager.jump')}
        >
          {Array.from({ length: pages }, (_, i) => i + 1).map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </label>

      <span className="w-px h-4 bg-slate-200 mx-0.5 flex-shrink-0" />
      <button className="pgbtn" style={{ padding: '0 8px' }} onClick={() => step(-1)} aria-label={t('pager.zoomOut')}>
        {ZOOM_OUT}
      </button>
      <span className="mono text-[10.5px] text-slate-400 num">{Math.round(zoom * 100)}%</span>
      <button className="pgbtn" style={{ padding: '0 8px' }} onClick={() => step(1)} aria-label={t('pager.zoomIn')}>
        {ZOOM_IN}
      </button>
    </div>
  )
}
