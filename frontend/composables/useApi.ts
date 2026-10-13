import type { CurrentUser } from '~/types/api'

const TOKEN_KEY = 'agent-workbench.token'

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function useAuth() {
  const token = useState<string | null>('auth-token', () => null)
  const user = useState<CurrentUser | null>('auth-user', () => null)

  const isAuthenticated = computed(() => Boolean(token.value))

  function restore(): void {
    if (!import.meta.client || token.value) return
    token.value = window.localStorage.getItem(TOKEN_KEY)
  }

  function adopt(value: string): void {
    token.value = value
    if (import.meta.client) window.localStorage.setItem(TOKEN_KEY, value)
  }

  function clear(): void {
    token.value = null
    user.value = null
    if (import.meta.client) window.localStorage.removeItem(TOKEN_KEY)
  }

  return { token, user, isAuthenticated, restore, adopt, clear }
}

export function useApi() {
  const config = useRuntimeConfig()
  const { token, clear } = useAuth()

  const apiBase = computed(() => String(config.public.apiBase || '').replace(/\/$/, ''))

  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers = new Headers(options.headers ?? {})
    if (token.value) headers.set('Authorization', `Bearer ${token.value}`)
    // Never set Content-Type for FormData: the browser must supply the multipart boundary.
    if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json')
    }

    const response = await fetch(`${apiBase.value}${path}`, { ...options, headers })

    if (response.status === 401) {
      clear()
      throw new ApiError('登录已过期，请重新登录', 401)
    }

    if (!response.ok) {
      throw new ApiError(await describeError(response), response.status)
    }

    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }

  return {
    apiBase,
    request,
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body?: unknown) =>
      request<T>(path, {
        method: 'POST',
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  }
}

async function describeError(response: Response): Promise<string> {
  try {
    const body = await response.json()
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          const entry = item as { loc?: unknown[]; msg?: string }
          const field = Array.isArray(entry.loc) ? entry.loc.slice(1).join('.') : ''
          return field ? `${field}: ${entry.msg ?? ''}` : (entry.msg ?? '')
        })
        .join('; ')
    }
  } catch {
    // fall through to the status text
  }
  return `请求失败（HTTP ${response.status}）`
}
