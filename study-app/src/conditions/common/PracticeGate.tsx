/**
 * Practice gate banner (FS-06, BE-18).
 *
 * Sits above the normal condition workspace during the practice phase and
 * lists what is still outstanding. The participant works with the practice
 * material -- a different criterion, two exhibits, no planted errors -- and
 * clears each gate by doing the thing, not by clicking an acknowledgement.
 *
 * The gates are the interactions the condition is *about*. Condition C has to
 * have opened the magnifier and followed a linkage jump at least once, because
 * someone who never discovers those is not really in condition C; condition B
 * has to have paged through a document by hand, which is its only route to the
 * evidence. Confirming you have read an instruction is not the same as having
 * done it, and only one of the two is checkable.
 *
 * State lives on the server (`/checkpoint`). A client-side tally is a tally a
 * reload clears, and this one decides whether someone may start the measured
 * task.
 */
import { useTranslation } from 'react-i18next'

interface Props {
  required: string[]
  cleared: string[]
  complete: boolean
}

export function PracticeGate({ required, cleared, complete }: Props) {
  const { t } = useTranslation()

  return (
    <div
      className="flex items-center gap-3 px-4 border-b bg-indigo-50 border-indigo-200"
      style={{ height: 'var(--h-status)' }}
    >
      <span className="text-[11px] font-bold text-indigo-700 tracking-widest flex-shrink-0">
        {t('practice.label')}
      </span>
      <span className="text-[12px] text-indigo-900 truncate">
        {complete ? t('practice.done') : t('practice.instruction')}
      </span>
      <div className="ml-auto flex items-center gap-2 flex-shrink-0">
        {required.map((gate) => {
          const done = cleared.includes(gate)
          return (
            <span
              key={gate}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11.5px] font-medium border ${
                done
                  ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                  : 'bg-white border-indigo-200 text-indigo-700'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${done ? 'bg-emerald-500' : 'bg-indigo-300'}`}
              />
              {t(`practice.gate.${gate}`)}
            </span>
          )
        })}
      </div>
    </div>
  )
}
