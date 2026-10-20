import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Button } from './ui/Button'

const KEY = 'astral.onboarded'

function seen(): boolean {
  try {
    return localStorage.getItem(KEY) === '1'
  } catch {
    return true
  }
}

/** Three-step first-visit tour for staff (T8.6): scope, then map modes, then priority. Shown once. */
export function Onboarding() {
  const { t } = useTranslation()
  const [step, setStep] = useState<number | null>(() => (seen() ? null : 0))
  const dialog = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    if (step !== null && !dialog.current?.open) dialog.current?.showModal()
  }, [step])

  function finish() {
    try {
      localStorage.setItem(KEY, '1')
    } catch {
      // Private mode: the tour shows again next visit, which is harmless.
    }
    dialog.current?.close()
    setStep(null)
  }

  if (step === null) return null
  const n = step + 1
  return (
    <dialog ref={dialog} aria-labelledby="tour-title" onCancel={finish}
      className="m-auto w-[min(28rem,calc(100%-2rem))] rounded border-t-4 border-marking bg-kerb p-6 text-asphalt shadow-xl backdrop:bg-asphalt/50">
      <p className="text-sm text-road">{t('onboarding.step', { n })}</p>
      <h2 id="tour-title" className="mt-1 text-xl font-semibold">{t(`onboarding.s${n}Title`)}</h2>
      <p className="mt-2 text-road">{t(`onboarding.s${n}Body`)}</p>
      <div className="mt-6 flex items-center justify-between gap-3">
        <Button variant="quiet" className="px-0" onClick={finish}>{t('onboarding.skip')}</Button>
        {n < 3
          ? <Button variant="primary" onClick={() => setStep(step + 1)}>{t('onboarding.next')}</Button>
          : <Button variant="primary" onClick={finish}>{t('onboarding.done')}</Button>}
      </div>
    </dialog>
  )
}
