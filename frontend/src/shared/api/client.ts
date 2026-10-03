/** Fetch wrapper for the FastAPI backend. Auth tokens come from Supabase Auth only. */

export class ApiError extends Error {
  readonly status: number
  readonly slug: string
  readonly detail: string | undefined
  readonly ruleId: string | undefined
  readonly sourceId: string | undefined
  readonly errors: { loc: (string | number)[]; msg: string; type: string }[] | undefined

  constructor(init: {
    status: number
    slug: string
    title: string
    detail?: string
    ruleId?: string
    sourceId?: string
    errors?: { loc: (string | number)[]; msg: string; type: string }[]
  }) {
    super(init.detail ?? init.title)
    this.name = 'ApiError'
    this.status = init.status
    this.slug = init.slug
    this.detail = init.detail
    this.ruleId = init.ruleId
    this.sourceId = init.sourceId
    this.errors = init.errors
  }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>

export interface Api {
  get<T>(path: string): Promise<T>
  patch<T>(path: string, body: unknown, options: { rowVersion: number }): Promise<T>
  post<T>(path: string, body: unknown): Promise<T>
}

async function toApiError(response: Response): Promise<ApiError> {
  try {
    const problem = await response.json()
    const type: string = typeof problem.type === 'string' ? problem.type : ''
    return new ApiError({
      status: response.status,
      slug: type.split('/').pop() || 'unknown',
      title: problem.title ?? response.statusText,
      detail: problem.detail,
      ruleId: problem.rule_id,
      sourceId: problem.source_id,
      errors: problem.errors,
    })
  } catch {
    return new ApiError({
      status: response.status,
      slug: 'unknown',
      title: response.statusText || 'Request failed',
    })
  }
}

export function createApi(
  getToken: () => Promise<string | null>,
  fetchImpl: FetchLike = (input, init) => fetch(input, init),
  baseUrl = '/api/v1',
): Api {
  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    rowVersion?: number,
  ): Promise<T> {
    const headers = new Headers({ accept: 'application/json' })
    const token = await getToken()
    if (token) headers.set('authorization', `Bearer ${token}`)
    if (body !== undefined) headers.set('content-type', 'application/json')
    if (rowVersion !== undefined) headers.set('if-match', `"${rowVersion}"`)
    const response = await fetchImpl(`${baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (!response.ok) throw await toApiError(response)
    if (response.status === 204) return undefined as T
    return (await response.json()) as T
  }
  return {
    get: (path) => request('GET', path),
    patch: (path, body, { rowVersion }) => request('PATCH', path, body, rowVersion),
    post: (path, body) => request('POST', path, body),
  }
}
