import { describe, expect, test } from 'vitest'
import { formatDate, formatDateTime, formatGbp, formatMass } from './format'

describe('formatDate (legal dates are UK dates, no time zone shifts)', () => {
  test('writes the month in words', () => {
    expect(formatDate('2027-03-14')).toBe('14 March 2027')
    expect(formatDate('2027-01-01')).toBe('1 January 2027')
    expect(formatDate('2028-02-29')).toBe('29 February 2028')
  })
  test('rejects impossible and malformed dates', () => {
    expect(() => formatDate('2027-02-30')).toThrow()
    expect(() => formatDate('14/03/2027')).toThrow()
    expect(() => formatDate('')).toThrow()
  })
})

describe('formatDateTime (instants are shown in UK time)', () => {
  test('BST evening is the next UK day', () => {
    expect(formatDateTime('2027-03-31T23:30:00Z')).toBe('1 April 2027, 00:30')
  })
  test('GMT keeps the same day', () => {
    expect(formatDateTime('2027-12-31T23:30:00Z')).toBe('31 December 2027, 23:30')
  })
  test('requires a time zone', () => {
    expect(() => formatDateTime('2027-03-31T23:30:00')).toThrow()
  })
})

describe('formatGbp (decimal strings, never floats)', () => {
  test.each([
    ['1234.56', '£1,234.56'],
    ['0', '£0.00'],
    ['0.5', '£0.50'],
    ['999', '£999.00'],
    ['1000', '£1,000.00'],
    ['50000.00', '£50,000.00'],
    ['1234567.891', '£1,234,567.89'],
    ['-1234.5', '-£1,234.50'],
    ['12345678901234567890.12', '£12,345,678,901,234,567,890.12'],
  ])('%s -> %s', (input, expected) => {
    expect(formatGbp(input)).toBe(expected)
  })
  test('shows exactly what was given, without rounding up', () => {
    expect(formatGbp('49999.999')).toBe('£49,999.99')
  })
  test('refuses numbers and malformed strings', () => {
    expect(() => formatGbp(1234.56 as unknown as string)).toThrow()
    expect(() => formatGbp('12,34')).toThrow()
    expect(() => formatGbp('abc')).toThrow()
    expect(() => formatGbp('')).toThrow()
  })
})

describe('formatMass', () => {
  test('groups thousands and keeps the given decimals', () => {
    expect(formatMass('48200.000000')).toBe('48,200.000000 kg')
    expect(formatMass('0.5')).toBe('0.5 kg')
  })
})
