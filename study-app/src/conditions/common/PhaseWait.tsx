/**
 * A phase with nothing for the participant to do: the moderator is talking,
 * setting something up, or the session is over.
 *
 * Deliberately bare. Anything on this screen would be something to read while
 * waiting, and time spent reading it is time not spent on the task -- but it
 * would still be inside the phase timings.
 */
import { useTranslation } from 'react-i18next'

interface Props {
  phaseKey: string
}

export function PhaseWait({ phaseKey }: Props) {
  const { t } = useTranslation()
  return (
    <div className="h-full grid place-items-center bg-slate-100">
      <div className="text-center">
        <p className="text-[15px] font-semibold text-slate-700 mb-1">{t(phaseKey)}</p>
        <p className="text-[13px] text-slate-500">{t('phase.waiting')}</p>
      </div>
    </div>
  )
}
