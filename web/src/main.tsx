import { GoogleOAuthProvider } from '@react-oauth/google'
import { StrictMode } from 'react'
import type { ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'
import { AuthProvider } from './features/auth/AuthContext'
import { GOOGLE_CLIENT_ID, GOOGLE_SIGN_IN_ENABLED } from './lib/config'
import './styles.css'

/**
 * The Google provider loads Identity Services and holds the client id.
 *
 * It is only mounted when a client id exists — the provider requires one, and
 * mounting it with an empty string produces a console error and a button that
 * silently never works, which is a worse failure than falling back to the
 * development sign-in.
 */
function WithGoogle({ children }: { children: ReactNode }) {
  if (!GOOGLE_SIGN_IN_ENABLED) return <>{children}</>
  return <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>{children}</GoogleOAuthProvider>
}

const container = document.getElementById('root')
if (!container) throw new Error('Missing #root element.')

createRoot(container).render(
  <StrictMode>
    <WithGoogle>
      <BrowserRouter>
        <AuthProvider>
          <App />
        </AuthProvider>
      </BrowserRouter>
    </WithGoogle>
  </StrictMode>,
)
