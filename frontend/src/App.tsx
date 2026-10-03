import { Navigate, Route, Routes } from 'react-router'
import { OpsHome } from './ops/OpsHome'
import { TenantShell } from './ops/TenantShell'
import { MfaChallenge } from './ops/pages/MfaChallenge'
import { MfaEnrol } from './ops/pages/MfaEnrol'
import { ResetPassword } from './ops/pages/ResetPassword'
import { SignIn } from './ops/pages/SignIn'
import { TasksPage } from './ops/pages/TasksPage'
import { TenantHome } from './ops/pages/TenantHome'
import { UpdatePassword } from './ops/pages/UpdatePassword'
import { PortalHome } from './portal/PortalHome'
import { ClientPage } from './ops/platform/ClientPage'
import { ClientsPage } from './ops/platform/ClientsPage'
import { PlatformShell } from './ops/platform/PlatformShell'
import { RequireAuth } from './shared/auth/RequireAuth'

export default function App() {
  return (
    <Routes>
      <Route path="/signin" element={<SignIn />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/reset-password/update" element={<UpdatePassword />} />
      <Route element={<RequireAuth />}>
        <Route path="/mfa/enrol" element={<MfaEnrol />} />
        <Route path="/mfa/challenge" element={<MfaChallenge />} />
        <Route path="/ops" element={<OpsHome />} />
        <Route path="/ops/platform" element={<PlatformShell />}>
          <Route index element={<ClientsPage />} />
          <Route path="tenants/:tenantId" element={<ClientPage />} />
        </Route>
        <Route path="/ops/t/:tenantId" element={<TenantShell />}>
          <Route index element={<TenantHome />} />
          <Route path="tasks" element={<TasksPage />} />
        </Route>
      </Route>
      <Route path="/portal/*" element={<PortalHome />} />
      <Route path="*" element={<Navigate to="/ops" replace />} />
    </Routes>
  )
}
