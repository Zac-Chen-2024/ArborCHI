/**
 * Router (D2, FS-02).
 *
 * The one rule that matters here: the URL does not choose the condition. A
 * participant whose token says "b" and who types /c is redirected to /b. The
 * check is `state.condition !== want`, evaluated on every render against the
 * server's answer, so tampering has no window.
 *
 * The soft lock is also rendered here rather than inside the conditions, so
 * neither condition can forget it (FS-06).
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, Route, BrowserRouter as Router, Routes, useNavigate } from 'react-router-dom'

import { ConditionB } from './conditions/b/ConditionB'
import { ConditionC } from './conditions/c/ConditionC'
import { ConfidenceForm } from './conditions/common/ConfidenceForm'
import { PhaseWait } from './conditions/common/PhaseWait'
import { ProbeRunner } from './conditions/common/ProbeRunner'
import { Join } from './routes/Join'
import { Moderator } from './routes/Moderator'
import { BUILD_HASH, useSession } from './lib/session'
import { logger } from './lib/logger'
import { fetchMaterial, type Material } from './lib/material'
import type { Condition, StudyState } from './lib/api'

function SoftLockOverlay() {
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 z-[90] bg-slate-900/45 backdrop-blur-[2px] grid place-items-center">
      <div className="bg-white rounded-xl shadow-xl border border-slate-200 px-8 py-6 text-center max-w-[380px]">
        <p className="text-[14px] font-semibold text-slate-800 mb-1">{t('phase.softlock')}</p>
        <p className="text-[12.5px] text-slate-500">{t('phase.waiting')}</p>
      </div>
    </div>
  )
}

/** Guards one condition route. Renders only if the token agrees. */
function ConditionRoute({ want }: { want: Condition }) {
  const { state, loading, error } = useSession()
  const navigate = useNavigate()

  useEffect(() => {
    logger.start(BUILD_HASH)
    const stop = useSession.getState().startPolling()
    return stop
  }, [])

  useEffect(() => {
    if (error) navigate('/join', { replace: true })
  }, [error, navigate])

  if (loading || !state) return null
  // D2: the server's answer wins over whatever the address bar says.
  if (state.condition !== want) return <Navigate to={`/${state.condition}`} replace />

  return (
    <>
      <PhaseScreen state={state} want={want} />
      {state.softlock && <SoftLockOverlay />}
    </>
  )
}

/**
 * Which screen a phase gets.
 *
 * The confidence and probe phases replace the workspace entirely rather than
 * appearing over it. Leaving the draft visible during the probe would let a
 * participant re-read the surrounding paragraphs while judging one sentence,
 * and "did they check the source" -- the thing being measured -- would stop
 * meaning anything.
 */
function PhaseScreen({ state, want }: { state: StudyState; want: Condition }) {
  const [material, setMaterial] = useState<Material | null>(null)

  useEffect(() => {
    if (state.phase !== 'probe') return
    void fetchMaterial().then(setMaterial)
  }, [state.phase])

  if (state.phase === 'confidence') {
    // Advancing is the moderator's job; the participant just waits after
    // answering, so the phase machine stays the single source of order.
    return <ConfidenceForm onDone={() => void useSession.getState().refresh()} />
  }
  if (state.phase === 'probe') {
    if (!material) return null
    return <ProbeRunner material={material} onDone={() => void useSession.getState().refresh()} />
  }
  if (state.phase === 'done') return <PhaseWait phaseKey="phase.done" />

  return want === 'c' ? <ConditionC state={state} /> : <ConditionB state={state} />
}

export default function App() {
  return (
    <Router>
      <Routes>
        <Route path="/join" element={<Join />} />
        <Route path="/c" element={<ConditionRoute want="c" />} />
        <Route path="/b" element={<ConditionRoute want="b" />} />
        <Route path="/mod" element={<Moderator />} />
        <Route path="*" element={<Navigate to="/join" replace />} />
      </Routes>
    </Router>
  )
}
