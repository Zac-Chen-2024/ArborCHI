/**
 * Pager, 48px. Prev / position / next plus the zoom stepper (FS-05).
 *
 * Page moves made here report `via: "click"`; the same move triggered by a
 * citation or chip reports `via: "linkage"`, which is how the analysis tells
 * a participant's own navigation apart from the system's (C-08).
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
      <button className="pgbtn" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        {t('pager.prev')}
      </button>
      <span className="mono text-[11px] text-slate-500 flex-1 text-center">
        {t('pager.pos', { ex: exhibit, i: page, n: pages })}
      </span>
      <button className="pgbtn" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        {t('pager.next')}
      </button>
      <span className="w-px h-4 bg-slate-200 mx-0.5" />
      <button className="pgbtn" style={{ padding: '0 8px' }} onClick={() => step(-1)} aria-label={t('pager.zoomOut')}>
        {ZOOM_OUT}
      </button>
      <span className="mono text-[10.5px] text-slate-400">{Math.round(zoom * 100)}%</span>
      <button className="pgbtn" style={{ padding: '0 8px' }} onClick={() => step(1)} aria-label={t('pager.zoomIn')}>
        {ZOOM_IN}
      </button>
    </div>
  )
}
