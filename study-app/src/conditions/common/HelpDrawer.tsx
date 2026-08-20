/**
 * Help drawer. Same shell in both conditions; the "linkage" panel is replaced
 * by a "how to find evidence" panel in B, because B has no linkage to explain.
 */
import { useTranslation } from 'react-i18next'

import type { Condition } from '../../lib/api'

interface Props {
  open: boolean
  condition: Condition
  onClose: () => void
}

export function HelpDrawer({ open, condition, onClose }: Props) {
  const { t } = useTranslation()

  return (
    <div
      id="drawer"
      className={`fixed left-0 right-0 bottom-0 bg-white border-t border-slate-300 shadow-2xl px-6 py-5${open ? ' open' : ''}`}
      style={{ zIndex: 80 }}
      aria-hidden={!open}
    >
      <div className="flex items-start gap-8 max-w-[1600px] mx-auto">
        {condition === 'c' && (
          <div className="flex-1">
            <p className="text-[13px] font-bold mb-2">{t('help.hierarchy')}</p>
            <p className="text-[12.5px] text-slate-600 leading-relaxed">{t('help.hierarchyBody')}</p>
          </div>
        )}
        <div className="flex-1">
          <p className="text-[13px] font-bold mb-2">
            {condition === 'c' ? t('help.linkage') : t('help.manual')}
          </p>
          <p className="text-[12.5px] text-slate-600 leading-relaxed">
            {condition === 'c' ? t('help.linkageBody') : t('help.manualBody')}
          </p>
        </div>
        <button onClick={onClose} className="px-3 py-1.5 rounded-lg border border-slate-200 text-[12px] text-slate-600">
          {t('help.close')}
        </button>
      </div>
    </div>
  )
}
