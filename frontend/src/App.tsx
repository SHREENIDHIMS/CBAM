import { Navigate, Route, Routes } from 'react-router'
import { BatchDetailPage } from './ops/imports/BatchDetailPage'
import { BatchListPage } from './ops/imports/BatchListPage'
import { LedgerPage } from './ops/imports/LedgerPage'
import { LineDetailPage } from './ops/imports/LineDetailPage'
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
import { DatasetPage } from './ops/refdata/DatasetPage'
import { RefDataShell } from './ops/refdata/RefDataShell'
import { ReferenceDataPage } from './ops/refdata/ReferenceDataPage'
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
        <Route path="/ops/reference-data" element={<RefDataShell />}>
          <Route index element={<ReferenceDataPage />} />
          <Route path=":dataset" element={<DatasetPage />} />
        </Route>
        <Route path="/ops/t/:tenantId" element={<TenantShell />}>
          <Route index element={<TenantHome />} />
          <Route path="tasks" element={<TasksPage />} />
          <Route path="imports" element={<BatchListPage />} />
          <Route path="imports/lines" element={<LedgerPage />} />
          <Route path="imports/lines/:lineId" element={<LineDetailPage />} />
          <Route path="imports/:batchId" element={<BatchDetailPage />} />
        </Route>
      </Route>
      <Route path="/portal/*" element={<PortalHome />} />
      <Route path="*" element={<Navigate to="/ops" replace />} />
    </Routes>
  )
}
