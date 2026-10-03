import { Navigate, Route, Routes } from 'react-router'
import { OpsHome } from './ops/OpsHome'
import { PortalHome } from './portal/PortalHome'

export default function App() {
  return (
    <Routes>
      <Route path="/ops/*" element={<OpsHome />} />
      <Route path="/portal/*" element={<PortalHome />} />
      <Route path="*" element={<Navigate to="/ops" replace />} />
    </Routes>
  )
}
