import { describe, expect, test } from 'vitest'
import { EORI_PATTERN, isRealDate } from './validate'

describe('validators', () => {
  test('EORI pattern', () => {
    expect(EORI_PATTERN.test('GB123456789012')).toBe(true)
    expect(EORI_PATTERN.test('XI123456789012')).toBe(true)
    expect(EORI_PATTERN.test('FR123456789012')).toBe(false)
    expect(EORI_PATTERN.test('GB12345678901')).toBe(false)
  })
  test('real dates only', () => {
    expect(isRealDate('2028-02-29')).toBe(true)
    expect(isRealDate('2027-02-29')).toBe(false)
    expect(isRealDate('2027-13-45')).toBe(false)
    expect(isRealDate('27-1-1')).toBe(false)
  })
})
