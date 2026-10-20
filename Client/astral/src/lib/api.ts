// Fetch wrapper: adds the Clerk token and unwraps the error envelope (spec-api §1).

export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000/api/v1'

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

export type TokenGetter = () => Promise<string | null>

type Params = Record<string, string | number | boolean | undefined | null>

export interface FetchOptions {
  method?: string
  params?: Params
  body?: unknown
  /** Sent as multipart/form-data instead of JSON (photo uploads, CSV imports). */
  form?: FormData
  /** Return the raw Response (for file downloads). */
  raw?: boolean
}

export async function apiFetch<T>(path: string, getToken: TokenGetter, options: FetchOptions = {}): Promise<T> {
  const url = new URL(API_BASE + path)
  for (const [key, value] of Object.entries(options.params ?? {})) {
    if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value))
  }
  const headers: Record<string, string> = {}
  const token = await getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'

  let res: Response
  try {
    res = await fetch(url, {
      method: options.method ?? (options.form ? 'POST' : 'GET'),
      headers,
      body: options.form ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
    })
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', 'Cannot reach the server')
  }
  if (options.raw && res.ok) return res as T
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    const err = data?.error ?? {}
    throw new ApiError(res.status, err.code ?? 'ERROR', err.message ?? res.statusText, err.details)
  }
  return data as T
}
