import { createContext, useContext, useState, type ReactNode } from 'react'

// State › District scope, remembered between sessions (spec §9.1 Memory).
export interface Scope {
  state: string
  district: string
}

const KEY = 'scope'
// The focus area (plan A2): Perak › Perak Tengah, where UTP Seri Iskandar is. District IDs are stable uuid5s.
const PERAK_TENGAH = 'fb490628-e926-5cdd-a695-047e862a4bc0'
const DEFAULT: Scope = { state: 'A', district: PERAK_TENGAH }

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
