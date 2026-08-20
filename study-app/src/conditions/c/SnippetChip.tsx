/**
 * Evidence chip (C-05). Two states, and the distinction is the whole point:
 *
 *   hover  -> `is-preview`, dashed. The left panel previews the passage; the
 *             focus is NOT committed and reverts on mouse-out.
 *   click  -> `is-focus`, solid. The focus is committed: left panel locates,
 *             right panel highlights the paragraph, breadcrumb updates.
 *
 * The analysis separates "looked" from "chose to look", so these stay two
 * distinct events rather than one debounced blur (日志手册 §4).
 */
import { useTranslation } from 'react-i18next'

import type { Snippet } from '../../lib/material'

interface Props {
  snippet: Snippet
  committed: boolean
  previewing: boolean
  onHoverStart: () => void
  onHoverEnd: () => void
  onClick: () => void
  onZoom: () => void
}

export function SnippetChip({
  snippet,
  committed,
  previewing,
  onHoverStart,
  onHoverEnd,
  onClick,
  onZoom,
}: Props) {
  const { t } = useTranslation()
  const cls = `chip${committed ? ' is-focus' : ''}${previewing && !committed ? ' is-preview' : ''}`

  return (
    <button
      className={cls}
      onMouseEnter={onHoverStart}
      onMouseLeave={onHoverEnd}
      onClick={(e) => {
        e.stopPropagation()
        onClick()
      }}
    >
      <span className={`mono text-[10.5px] font-semibold ${committed ? 'text-blue-600' : 'text-blue-500'}`}>
        {t('ref.exPage', { ex: snippet.exhibit, i: snippet.page })}
      </span>{' '}
      {snippet.label}
      <span
        className="zoom"
        role="button"
        tabIndex={-1}
        aria-label={t('lightbox.open')}
        onClick={(e) => {
          e.stopPropagation()
          onZoom()
        }}
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-3.5-3.5M11 8v6M8 11h6" />
        </svg>
      </span>
    </button>
  )
}
