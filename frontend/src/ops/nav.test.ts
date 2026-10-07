import { describe, expect, test } from 'vitest'
import { visibleNav } from './nav'

const labels = (permissions: string[]) => visibleNav(new Set(permissions)).map((i) => i.label)

describe('role-aware navigation', () => {
  test('everyone in a tenant sees Home', () => {
    expect(labels([])).toEqual(['Home'])
  })
  test('Tasks needs tasks:read', () => {
    expect(labels(['tasks:read'])).toEqual(['Home', 'Tasks'])
    expect(labels(['imports:read'])).not.toContain('Tasks')
  })
  test('Imports needs imports:read', () => {
    expect(labels(['imports:read'])).toEqual(['Home', 'Imports', 'Import ledger'])
    expect(labels(['tasks:read'])).not.toContain('Imports')
  })
  test('links are relative to the tenant', () => {
    const items = visibleNav(new Set(['tasks:read']))
    expect(items.map((i) => i.to)).toEqual(['', 'tasks'])
  })
})
