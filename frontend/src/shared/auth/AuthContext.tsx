import { createContext, useContext } from 'react'

export interface AuthUser {
  id: string
  email: string | undefined
}

export interface MfaEnrolment {
  factorId: string
  qrCodeDataUrl: string
  secret: string
}

export interface AuthApi {
  status: 'loading' | 'signed_out' | 'signed_in'
  user: AuthUser | null
  /** Current assurance level of this session: 'aal2' once MFA has been passed. */
  aal: 'aal1' | 'aal2' | null
  getAccessToken(): Promise<string | null>
  signIn(email: string, password: string): Promise<void>
  signOut(): Promise<void>
  requestPasswordReset(email: string): Promise<void>
  updatePassword(password: string): Promise<void>
  mfa: {
    listVerifiedFactors(): Promise<{ id: string }[]>
    enrol(): Promise<MfaEnrolment>
    /** Challenge and verify a six-digit code; on success the session becomes aal2. */
    verify(factorId: string, code: string): Promise<void>
  }
}

export const AuthContext = createContext<AuthApi | null>(null)

export function useAuth(): AuthApi {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside an AuthContext provider')
  return value
}
