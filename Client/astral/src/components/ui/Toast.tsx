import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

export interface ToastAction {
  label: string
  onClick: () => void
}

interface Toast {
  message: string
  action?: ToastAction
  ms: number
}

type Show = (message: string, action?: ToastAction, ms?: number) => void

const ToastContext = createContext<Show>(() => {})

/** Confirms an action in its own words ("Marked verified"); an optional action such as Undo
 * stays available until the toast clears (10 s for undo, spec §9.1 Learning). */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null)
  const show = useCallback<Show>((message, action, ms = action ? 10_000 : 4000) => setToast({ message, action, ms }), [])

  useEffect(() => {
    if (!toast) return
    const id = window.setTimeout(() => setToast(null), toast.ms)
    return () => window.clearTimeout(id)
  }, [toast])

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-6 left-1/2 z-[2000] -translate-x-1/2">
        {toast && (
          <div className="pointer-events-auto flex items-center gap-4 rounded bg-asphalt px-4 py-3 text-sm text-kerb shadow-lg">
            <span>{toast.message}</span>
            {toast.action && (
              <button type="button" className="min-h-11 rounded px-2 font-semibold text-marking underline underline-offset-4"
                onClick={() => { toast.action?.onClick(); setToast(null) }}>
                {toast.action.label}
              </button>
            )}
          </div>
        )}
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)
