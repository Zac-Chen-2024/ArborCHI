/** Exhibit chip row, 42px (FS-05). Manual navigation -- identical in C and B. */
import { useTranslation } from 'react-i18next'

import type { Exhibit } from '../../../data/fixtures'

interface Props {
  exhibits: Exhibit[]
  active: string
  onClick: (id: string) => void
}

export function ExhibitStrip({ exhibits, active, onClick }: Props) {
  const { t } = useTranslation()

  return (
    <div className="exstrip">
      {exhibits.map((ex) => (
        <button
          key={ex.id}
          className={`exchip${ex.id === active ? ' active' : ''}`}
          onClick={() => onClick(ex.id)}
          title={ex.title}
        >
          <span className="mono">{ex.id}</span>
          <span className="pgs">{t('ref.pages', { n: ex.pages })}</span>
        </button>
      ))}
    </div>
  )
}
