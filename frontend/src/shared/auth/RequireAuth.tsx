import { useQuery } from '@tanstack/react-query'
import { Navigate, Outlet, useLocation } from 'react-router'
import { useMe } from '../api/queries'
import { useAuth } from './AuthContext'

/** Gate for signed-in areas: sign in, then MFA where the user's roles need it. */
export function RequireAuth() {
  const auth = useAuth()
  const location = useLocation()
  const signedIn = auth.status === 'signed_in'
  const me = useMe(signedIn)
  const factors = useQuery({
    queryKey: ['mfa-factors'],
    queryFn: () => auth.mfa.listVerifiedFactors(),
    enabled: signedIn,
  })

  if (auth.status === 'loading')
    return (
      <p role="status" className="p-6">
        Loading…
      </p>
    )
  if (!signedIn) return <Navigate to="/signin" replace state={{ from: location.pathname }} />
  if (me.isError)
    return (
      <p role="alert" className="p-6">
        We could not load your account. Please try again.
      </p>
    )
  if (me.isPending || factors.isPending)
    return (
      <p role="status" className="p-6">
        Loading…
      </p>
    )

  const needsMfa = me.data.mfa.required && auth.aal !== 'aal2'
  if (needsMfa && !location.pathname.startsWith('/mfa')) {
    const target = (factors.data?.length ?? 0) > 0 ? '/mfa/challenge' : '/mfa/enrol'
    return <Navigate to={target} replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}
