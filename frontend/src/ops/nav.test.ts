import { describe, expect, test } from 'vitest'
import { NAV_ITEMS, isNavActive, visibleNav } from './nav'

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

describe('active item', () => {
  const base = '/ops/t/t1'
  const active = (path: string) =>
    NAV_ITEMS.filter((i) => isNavActive(i, `${base}${path}`, base)).map((i) => i.label)
  test('exactly one item is active on each import page', () => {
    expect(active('')).toEqual(['Home'])
    expect(active('/imports')).toEqual(['Imports'])
    expect(active('/imports/abc')).toEqual(['Imports'])
    expect(active('/imports/lines')).toEqual(['Import ledger'])
    expect(active('/imports/lines/abc')).toEqual(['Import ledger'])
  })
})
