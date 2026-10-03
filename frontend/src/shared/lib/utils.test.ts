import { expect, test } from 'vitest'
import { cn } from './utils'

test('cn merges conflicting tailwind classes', () => {
  const hidden = Math.random() > 2
  expect(cn('px-2', 'px-4', hidden && 'hidden')).toBe('px-4')
})
