import { describe, expect, test, vi } from 'vitest'
import { ApiError, createApi } from './client'

function jsonResponse(body: unknown, init: ResponseInit & { contentType?: string } = {}) {
  const { contentType = 'application/json', ...rest } = init
  return new Response(JSON.stringify(body), { headers: { 'content-type': contentType }, ...rest })
}

describe('createApi', () => {
  test('sends the bearer token and returns JSON', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ ok: true }))
    const api = createApi(async () => 'tok', fetchImpl)
    await expect(api.get('/me')).resolves.toEqual({ ok: true })
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/v1/me')
    expect(new Headers(init.headers).get('authorization')).toBe('Bearer tok')
  })

  test('sends no authorization header when signed out', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}))
    await createApi(async () => null, fetchImpl).get('/health')
    expect(new Headers(fetchImpl.mock.calls[0][1].headers).has('authorization')).toBe(false)
  })

  test('PATCH sends If-Match with the row version and a JSON body', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ row_version: 3 }))
    const api = createApi(async () => 't', fetchImpl)
    await api.patch('/tenants/x/tasks/y', { status: 'done' }, { rowVersion: 2 })
    const [, init] = fetchImpl.mock.calls[0]
    const headers = new Headers(init.headers)
    expect(init.method).toBe('PATCH')
    expect(headers.get('if-match')).toBe('"2"')
    expect(headers.get('content-type')).toBe('application/json')
    expect(init.body).toBe('{"status":"done"}')
  })

  test('turns problem+json into an ApiError with rule and source', async () => {
    const problem = {
      type: 'https://cbam.example/errors/rule-blocked',
      title: 'A rule blocks this action',
      status: 409,
      detail: 'Default to actual is not allowed',
      rule_id: 'R3-014',
      source_id: 'FA2026-S17-P8-2',
    }
    const fetchImpl = vi
      .fn()
      .mockResolvedValue(
        jsonResponse(problem, { status: 409, contentType: 'application/problem+json' }),
      )
    const error = await createApi(async () => 't', fetchImpl)
      .get('/x')
      .catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    const apiError = error as ApiError
    expect(apiError.status).toBe(409)
    expect(apiError.slug).toBe('rule-blocked')
    expect(apiError.ruleId).toBe('R3-014')
    expect(apiError.sourceId).toBe('FA2026-S17-P8-2')
    expect(apiError.detail).toBe('Default to actual is not allowed')
  })

  test('copes with a non-JSON error body', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('Bad gateway', { status: 502 }))
    const error = (await createApi(async () => 't', fetchImpl)
      .get('/x')
      .catch((e: unknown) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(502)
    expect(error.slug).toBe('unknown')
  })

  test('DELETE sends the right method and resolves on 204', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    await expect(
      createApi(async () => 't', fetchImpl).delete('/platform/x'),
    ).resolves.toBeUndefined()
    expect(fetchImpl.mock.calls[0][1].method).toBe('DELETE')
  })

  test('204 resolves to undefined', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    await expect(createApi(async () => 't', fetchImpl).get('/x')).resolves.toBeUndefined()
  })
})

describe('createApi.getText', () => {
  test('sends the token and the accept type, and returns the body as text', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('a,b\r\n1,2\r\n'))
    const api = createApi(async () => 'tok', fetchImpl)
    await expect(api.getText('/x?format=csv', 'text/csv')).resolves.toBe('a,b\r\n1,2\r\n')
    const [url, init] = fetchImpl.mock.calls[0]
    expect(url).toBe('/api/v1/x?format=csv')
    const headers = new Headers(init.headers)
    expect(headers.get('authorization')).toBe('Bearer tok')
    expect(headers.get('accept')).toBe('text/csv')
  })

  test('a failure is still an ApiError', async () => {
    const body = JSON.stringify({ type: 'https://x/errors/not-found', title: 'nf' })
    const fetchImpl = vi.fn().mockResolvedValue(new Response(body, { status: 404 }))
    const api = createApi(async () => 't', fetchImpl)
    await expect(api.getText('/x', 'text/csv')).rejects.toBeInstanceOf(ApiError)
  })
})
