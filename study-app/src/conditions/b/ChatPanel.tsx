/**
 * Writing assistant chat (B-01).
 *
 * The first exchange is NOT sent by this component. The server prepends
 * bootstrap_b.txt on the session's first call, so a participant who opens the
 * app sees a complete first answer without having typed anything -- and the
 * prompt that produced it is a versioned, hashed asset rather than a string in
 * the frontend (BE-09).
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { CHAT_FIXTURE } from '../../data/fixtures'

interface Props {
  onCopyToDraft: (text: string) => void
}

export function ChatPanel({ onCopyToDraft }: Props) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')

  return (
    <section className="panel bg-slate-100" style={{ gridTemplateRows: 'auto minmax(0,1fr) auto' }}>
      <div className="phead" style={{ padding: '0 20px' }}>
        <span className="text-[13.5px] font-bold text-slate-700 flex-shrink-0">{t('chat.title')}</span>
        <span className="text-[10.5px] px-2 py-0.5 rounded-full bg-indigo-50 border border-indigo-200 text-indigo-700 font-medium">
          {t('chat.badge')}
        </span>
      </div>

      <div className="scroll px-6 py-4 space-y-4">
        {CHAT_FIXTURE.map((msg, i) =>
          msg.role === 'user' ? (
            <div key={i} className="flex justify-end">
              <div className="msg-u max-w-[75%] px-4 py-2.5 text-[13px] leading-relaxed">{msg.text}</div>
            </div>
          ) : (
            <div key={i} className="flex">
              <div className="msg-a max-w-[85%] px-4 py-3">
                <p className="text-[13px] leading-[1.85] text-slate-800">{msg.lead}</p>
                {msg.body.length > 0 && (
                  <div className="mt-2.5 pt-2.5 border-t border-slate-100 text-[13px] leading-[1.85] text-slate-800 space-y-2.5">
                    {msg.body.map((para, j) => (
                      <p key={j}>{para}</p>
                    ))}
                    {msg.footnote && <p className="text-slate-400 text-[11.5px]">{msg.footnote}</p>}
                  </div>
                )}
                <div className="mt-3 flex items-center gap-2">
                  <button
                    onClick={() => onCopyToDraft([msg.lead, ...msg.body].join('\n\n'))}
                    className="px-3 py-1.5 rounded-md bg-indigo-600 hover:bg-indigo-500 text-white text-[12px] font-semibold"
                  >
                    {t('chat.copy')}
                  </button>
                  <button className="px-3 py-1.5 rounded-md border border-slate-200 bg-white text-[12px] text-slate-600">
                    {t('chat.regen')}
                  </button>
                </div>
              </div>
            </div>
          ),
        )}
      </div>

      <div className="px-5 py-3 bg-white border-t border-slate-200">
        <div className="flex items-end gap-2 rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 focus-within:border-indigo-400">
          <textarea
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={t('chat.placeholder')}
            className="flex-1 resize-none outline-none text-[13px] leading-relaxed text-slate-800 placeholder:text-slate-400 bg-transparent"
          />
          <button
            aria-label={t('chat.send')}
            className="w-8 h-8 rounded-lg bg-slate-900 hover:bg-slate-700 text-white flex items-center justify-center flex-shrink-0"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </div>
      </div>
    </section>
  )
}
