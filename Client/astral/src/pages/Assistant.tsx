import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { useApi } from '../app/auth'
import { Button, buttonClass } from '../components/ui/Button'
import { ErrorBox } from '../components/ui/Status'

interface Answer {
  answer: string
  segments: number[]
  tool_calls: { tool: string; args: Record<string, unknown> }[]
  disclaimer: string
}

interface Turn {
  role: 'user' | 'assistant'
  content: string
  segments?: number[]
  disclaimer?: string
  /** A question whose answer failed. It stays on screen but isn't sent as history (U1). */
  failed?: boolean
}

interface Question {
  message: string
  history: Turn[]
}

const asHistory = (turns: Turn[]) =>
  turns.filter((turn) => !turn.failed).slice(-6).map(({ role, content }) => ({ role, content }))

/** Decision Assistant (T7.3): plain-language questions, answers cite roads you can see on the map. */
export default function Assistant() {
  const { t, i18n } = useTranslation()
  const api = useApi()
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const ask = useMutation({
    mutationFn: ({ message, history }: Question) => api<Answer>('/ai/assistant', {
      method: 'POST',
      body: { message, history: asHistory(history), language: i18n.language === 'ms' ? 'ms' : 'en' },
    }),
    onSuccess: (a) => setTurns((ts) => [...ts, { role: 'assistant', content: a.answer, segments: a.segments, disclaimer: a.disclaimer }]),
    // The question stays where it was, marked unanswered, so Try again can resend it.
    onError: () => setTurns((ts) => ts.map((turn, i) => (i === ts.length - 1 && turn.role === 'user' ? { ...turn, failed: true } : turn))),
  })
  useEffect(() => { end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [turns, ask.isPending, ask.isError])

  function send(message: string) {
    const text = message.trim()
    if (!text || ask.isPending) return
    ask.mutate({ message: text, history: turns })
    setTurns((ts) => [...ts, { role: 'user', content: text }])
    setDraft('')
  }

  function retry() {
    const last = turns[turns.length - 1]
    if (!last || last.role !== 'user' || ask.isPending) return
    ask.mutate({ message: last.content, history: turns.slice(0, -1) })
    setTurns((ts) => ts.map((turn, i) => (i === ts.length - 1 ? { ...turn, failed: false } : turn)))
  }
  const submit = (e: FormEvent) => { e.preventDefault(); send(draft) }
  const examples = [t('assistant.example1'), t('assistant.example2'), t('assistant.example3')]

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col px-4 py-6">
      <h1 className="text-2xl font-semibold">{t('nav.assistant')}</h1>
      <p className="mt-1 max-w-prose text-road">{t('assistant.intro')}</p>
      <div className="mt-6 min-h-0 flex-1 space-y-4 overflow-auto" aria-live="polite">
        {turns.length === 0 && (
          <div>
            <p className="text-sm font-semibold">{t('assistant.try')}</p>
            <ul className="mt-2 space-y-2">
              {examples.map((e) => (
                <li key={e}><button type="button" onClick={() => send(e)} className="min-h-11 rounded border border-hairline bg-kerb px-3 text-left hover:border-asphalt">{e}</button></li>
              ))}
            </ul>
          </div>
        )}
        {turns.map((turn, i) => (
          <div key={i} className={turn.role === 'user' ? 'ml-auto max-w-[85%] rounded bg-asphalt px-4 py-3 text-kerb' : 'max-w-[95%] border-l-4 border-marking bg-kerb px-4 py-3'}>
            <p className="whitespace-pre-wrap">{turn.content}</p>
            {turn.failed && <p className="mt-1 text-xs text-kerb/80">{t('assistant.notAnswered')}</p>}
            {turn.segments && turn.segments.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                <Link to={`/map?highlight=${turn.segments.join(',')}`} className={buttonClass('secondary', 'min-h-10 text-sm')}>{t('assistant.showOnMap', { count: turn.segments.length })}</Link>
                {turn.segments.slice(0, 5).map((id) => (
                  <Link key={id} to={`/analysis/${id}`} className={buttonClass('quiet', 'min-h-10 px-2 text-sm')}>{t('assistant.segment', { id })}</Link>
                ))}
              </div>
            )}
            {turn.disclaimer && <p className="mt-2 text-xs text-road">{turn.disclaimer}</p>}
          </div>
        ))}
        {ask.isPending && <p className="text-road">{t('assistant.thinking')}</p>}
        {ask.isError && <ErrorBox error={ask.error} onRetry={retry} />}
        <div ref={end} />
      </div>
      <form onSubmit={submit} className="mt-4 flex gap-2 border-t border-hairline pt-4">
        <label htmlFor="ask" className="sr-only">{t('assistant.label')}</label>
        <input id="ask" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={600} placeholder={t('assistant.placeholder')}
          className="min-h-11 min-w-0 flex-1 rounded border border-road bg-kerb px-3" />
        <Button type="submit" variant="primary" disabled={!draft.trim() || ask.isPending}>{t('assistant.ask')}</Button>
      </form>
    </div>
  )
}
