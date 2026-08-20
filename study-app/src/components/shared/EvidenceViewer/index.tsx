/**
 * EvidenceViewer -- the physical guarantee behind "equal access, only the
 * linkage differs" (§D3, FS-05, B-03).
 *
 * ONE component serves both conditions. C passes `linkage` props; B does not.
 * The difference is a prop, not a fork, so nobody can drift the two apart:
 *
 *   condition C   linkage={{ snippet, preview }}  -> bbox highlight, jump-to
 *   condition B   linkage={undefined}             -> manual navigation only
 *
 * If you ever find yourself writing `if (condition === 'b')` inside this
 * subtree, the parity argument is broken -- pass a prop instead.
 */
import { useTranslation } from 'react-i18next'

import type { Exhibit, Snippet } from '../../../data/fixtures'
import { ExhibitStrip } from './ExhibitStrip'
import { PageView } from './PageView'
import { PagerBar } from './PagerBar'

export interface Linkage {
  /** The snippet whose bbox is highlighted on the page. */
  snippet: Snippet
  /** True while this is a hover preview rather than a committed click. */
  preview: boolean
}

interface Props {
  exhibits: Exhibit[]
  activeExhibit: string
  page: number
  zoom: number
  /** Present in C, absent in B. Drives the bbox highlight and nothing else. */
  linkage?: Linkage
  /** Header slot: C shows a breadcrumb, B shows the current document. */
  contextStrip: React.ReactNode
  title: string
  /** Set in C only: the magnifier button on the page (C-11). */
  onOpenLightbox?: () => void
  onExhibitClick: (id: string) => void
  onPageChange: (page: number, via: 'click' | 'scroll' | 'linkage') => void
  onZoom: (zoom: number) => void
  headerBadge?: React.ReactNode
}

export function EvidenceViewer({
  exhibits,
  activeExhibit,
  page,
  zoom,
  linkage,
  contextStrip,
  title,
  onOpenLightbox,
  onExhibitClick,
  onPageChange,
  onZoom,
  headerBadge,
}: Props) {
  const { t } = useTranslation()
  const current = exhibits.find((e) => e.id === activeExhibit) ?? exhibits[0]

  return (
    <>
      <div className="phead">
        <span className="text-[13.5px] font-bold text-slate-700">{title}</span>
        {headerBadge}
        <span className="ml-auto text-[11px] text-slate-400">
          {t('evidence.meta', { n: exhibits.length })}
        </span>
      </div>

      {contextStrip}

      <ExhibitStrip exhibits={exhibits} active={activeExhibit} onClick={onExhibitClick} />

      <PageView page={page} zoom={zoom} linkage={linkage} onOpenLightbox={onOpenLightbox} />

      <PagerBar
        exhibit={current.id}
        page={page}
        pages={current.pages}
        zoom={zoom}
        onPage={(p) => onPageChange(p, 'click')}
        onZoom={onZoom}
      />
    </>
  )
}
