import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from './features/auth/AuthContext'
import { Dashboard } from './routes/Dashboard'
import { SignIn } from './routes/SignIn'
import { Viewer } from './routes/Viewer'

export function App() {
  const { status } = useAuth()

  if (status === 'loading') {
    return (
      <div className="page">
        <main className="dashboard">
          <p className="muted">Loading…</p>
        </main>
      </div>
    )
  }

  if (status === 'signed-out') {
    return (
      <Routes>
        <Route path="*" element={<SignIn />} />
      </Routes>
    )
  }

  return (
    <Routes>
      <Route path="/" element={<Dashboard />} />
      <Route path="/projects/:projectId" element={<Viewer />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
