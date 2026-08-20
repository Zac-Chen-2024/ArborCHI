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
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, Route, BrowserRouter as Router, Routes, useNavigate } from 'react-router-dom'

import { ConditionB } from './conditions/b/ConditionB'
import { ConditionC } from './conditions/c/ConditionC'
import { Join } from './routes/Join'
import { Moderator } from './routes/Moderator'
import { useSession } from './lib/session'
import type { Condition } from './lib/api'

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
      {want === 'c' ? <ConditionC state={state} /> : <ConditionB state={state} />}
      {state.softlock && <SoftLockOverlay />}
    </>
  )
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
