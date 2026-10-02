import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, test } from 'vitest'
import App from './App'

test('portal route renders the supplier portal', () => {
  render(
    <MemoryRouter initialEntries={['/portal']}>
      <App />
    </MemoryRouter>,
  )
  expect(screen.getByRole('heading', { name: 'Supplier portal' })).toBeInTheDocument()
})
