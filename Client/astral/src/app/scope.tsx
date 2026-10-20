import { createContext, useContext, useState, type ReactNode } from 'react'

// State › District scope, remembered between sessions (spec §9.1 Memory).
export interface Scope {
  state: string
  district: string
}

const KEY = 'scope'
const DEFAULT: Scope = { state: 'A', district: '' }

function load(): Scope {
  try {
    return { ...DEFAULT, ...JSON.parse(localStorage.getItem(KEY) ?? '{}') }
  } catch {
    return DEFAULT
  }
}

const ScopeContext = createContext<[Scope, (s: Scope) => void]>([DEFAULT, () => {}])

export function ScopeProvider({ children }: { children: ReactNode }) {
  const [scope, setScopeState] = useState<Scope>(load)
  const setScope = (next: Scope) => {
    setScopeState(next)
    try {
      localStorage.setItem(KEY, JSON.stringify(next))
    } catch {
      // storage blocked: scope just isn't remembered
    }
  }
  return <ScopeContext.Provider value={[scope, setScope]}>{children}</ScopeContext.Provider>
}

export const useScope = () => useContext(ScopeContext)
