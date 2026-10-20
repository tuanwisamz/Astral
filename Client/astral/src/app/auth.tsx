import { ClerkProvider, useAuth, useClerk, useUser } from '@clerk/clerk-react'
import { useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useMemo, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { apiFetch, type TokenGetter } from '../lib/api'

const CLERK_KEY: string | undefined = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY || undefined

/** True when sign-in is connected. Without a key, local development relies on the API's DEV_AUTH_ROLE. */
export const AUTH_CONFIGURED = Boolean(CLERK_KEY)

export type Role = 'public' | 'officer' | 'viewer' | 'admin'
const STAFF: Role[] = ['officer', 'viewer', 'admin']

export interface AuthState {
  configured: boolean
  isLoaded: boolean
  isSignedIn: boolean
  /** 'dev' only in local development without Clerk: every page is reachable. */
  role: Role | 'dev'
  email: string | null
  signOut: (redirectUrl?: string) => Promise<void>
  /** Saves the language to the account so it follows the person to other devices (plan A3). */
  saveLanguage: (lang: string) => Promise<void>
}

const DEV_STATE: AuthState = {
  configured: false,
  isLoaded: true,
  isSignedIn: false,
  role: import.meta.env.DEV ? 'dev' : 'public',
  email: null,
  signOut: async () => {},
  saveLanguage: async () => {},
}

const noToken: TokenGetter = async () => null
const TokenContext = createContext<TokenGetter>(noToken)
const AuthStateContext = createContext<AuthState>(DEV_STATE)

export const isStaff = (role: AuthState['role']) => role === 'dev' || STAFF.includes(role)

/** Where a person lands after signing in, or when they open "/" (spec FR-ACC-05). */
export const landingFor = (role: AuthState['role']) => (isStaff(role) ? '/' : '/map')

function ClerkBridge({ children }: { children: ReactNode }) {
  const { getToken, isLoaded, isSignedIn } = useAuth()
  const { user } = useUser()
  const clerk = useClerk()
  const queryClient = useQueryClient()

  const signOut = useCallback(async (redirectUrl = '/sign-in') => {
    await clerk.signOut({ redirectUrl })
    queryClient.clear() // nothing from the last account stays on screen
  }, [clerk, queryClient])

  const { i18n } = useTranslation()
  const savedLang = user?.unsafeMetadata?.lang as string | undefined
  const saveLanguage = useCallback(async (lang: string) => {
    if (user && savedLang !== lang) await user.update({ unsafeMetadata: { ...user.unsafeMetadata, lang } })
  }, [user, savedLang])
  // On sign-in, the account's language wins over this browser's.
  useEffect(() => {
    if (savedLang && savedLang !== i18n.language) {
      void i18n.changeLanguage(savedLang)
      try {
        localStorage.setItem('lang', savedLang)
      } catch {
        // not remembered on this device; the account still has it
      }
    }
  }, [savedLang, i18n])

  // The role is read for display and routing only; the API enforces it (spec NFR-08).
  const metaRole = user?.publicMetadata?.role as Role | undefined
  const state = useMemo<AuthState>(
    () => ({
      configured: true,
      isLoaded,
      isSignedIn: Boolean(isSignedIn),
      role: metaRole && (['public', ...STAFF] as string[]).includes(metaRole) ? metaRole : 'public',
      email: user?.primaryEmailAddress?.emailAddress ?? null,
      signOut,
      saveLanguage,
    }),
    [isLoaded, isSignedIn, metaRole, user, signOut, saveLanguage],
  )

  return (
    <TokenContext.Provider value={getToken}>
      <AuthStateContext.Provider value={state}>{children}</AuthStateContext.Provider>
    </TokenContext.Provider>
  )
}

/** Must sit inside the router, so Clerk navigates with React Router (architechture.md §4.6). */
export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  if (!CLERK_KEY) {
    return (
      <TokenContext.Provider value={noToken}>
        <AuthStateContext.Provider value={DEV_STATE}>{children}</AuthStateContext.Provider>
      </TokenContext.Provider>
    )
  }
  return (
    <ClerkProvider
      publishableKey={CLERK_KEY}
      routerPush={(to) => navigate(to)}
      routerReplace={(to) => navigate(to, { replace: true })}
      signInUrl="/sign-in"
      signUpUrl="/register"
      signInFallbackRedirectUrl="/"
      signUpFallbackRedirectUrl="/"
    >
      <ClerkBridge>{children}</ClerkBridge>
    </ClerkProvider>
  )
}

export const useAuthState = () => useContext(AuthStateContext)

export function useApi() {
  const getToken = useContext(TokenContext)
  return useCallback(
    <T,>(path: string, options?: Parameters<typeof apiFetch>[2]) => apiFetch<T>(path, getToken, options),
    [getToken],
  )
}
