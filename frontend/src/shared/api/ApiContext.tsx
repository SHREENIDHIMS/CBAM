import { createContext, useContext } from 'react'
import type { Api } from './client'

export const ApiContext = createContext<Api | null>(null)

export function useApi(): Api {
  const value = useContext(ApiContext)
  if (!value) throw new Error('useApi must be used inside an ApiContext provider')
  return value
}
