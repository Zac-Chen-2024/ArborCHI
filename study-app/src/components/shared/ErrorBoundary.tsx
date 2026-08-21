/**
 * Last line of defence for a session in progress.
 *
 * React unmounts the entire tree when a render throws. In this app that means
 * a participant, mid-task, watches the top bar, the evidence, the argument
 * structure and the letter vanish and get a white page -- and a moderator has
 * no way to tell that from a crashed browser. It happened for a one-character
 * reason: a bundle omitted an optional key and a panel read straight through
 * the missing container.
 *
 * So: catch, log the crash into the study log while the logger is still alive
 * (that record is the only thing that will say why the session ended where it
 * did), and show something that tells the participant to call the researcher
 * instead of a blank page.
 *
 * Deliberately NOT offering a retry. Re-rendering the same state re-throws, and
 * a button that appears to do nothing is worse than no button. Reloading is the
 * moderator's call, and the working tree now survives it.
 */
import { Component, type ErrorInfo, type ReactNode } from 'react'

import i18n from '../../i18n'
import { logger } from '../../lib/logger'

interface Props {
  children: ReactNode
}

interface State {
  crashed: boolean
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { crashed: false }

  static getDerivedStateFromError(): State {
    return { crashed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    logger.log('client_error', {
      message: String(error?.message ?? error),
      // Where it broke matters more than the full stack, which is minified in
      // a build and enormous in dev.
      component_stack: (info?.componentStack ?? '').split('\n').slice(0, 6).join(' | '),
      stack: (error?.stack ?? '').split('\n').slice(0, 4).join(' | '),
    })
    void logger.flush()
  }

  render(): ReactNode {
    if (!this.state.crashed) return this.props.children
    return (
      <div className="h-full grid place-items-center bg-slate-100">
        <div className="text-center max-w-[420px] px-8">
          <p className="text-[15px] font-semibold text-slate-700 mb-1">
            {i18n.t('crash.title')}
          </p>
          <p className="text-[13px] text-slate-500">
            {i18n.t('crash.body')}
          </p>
        </div>
      </div>
    )
  }
}
