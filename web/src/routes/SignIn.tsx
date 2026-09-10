import { GoogleLogin } from '@react-oauth/google'
import { useState } from 'react'

import { useAuth } from '../features/auth/AuthContext'
import { GOOGLE_SIGN_IN_ENABLED } from '../lib/config'

export function SignIn() {
  const { signInWithGoogle, signInAsDeveloper } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [email, setEmail] = useState('')

  const onGoogleSuccess = async (credential: string | undefined) => {
    if (!credential) {
      setError('Google did not return a credential. Please try again.')
      return
    }
    setError(null)
    setBusy(true)
    try {
      await signInWithGoogle(credential)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign you in.')
      setBusy(false)
    }
  }

  const onDeveloperSignIn = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await signInAsDeveloper(email.trim())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not sign you in.')
      setBusy(false)
    }
  }

  return (
    <main className="signin">
      <div className="signin-card">
        <h1 className="signin-title">Drawing Annotator</h1>
        <p className="signin-lede">
          Mark up construction drawing sets. Block what should stay private, capture what should be
          read.
        </p>

        {GOOGLE_SIGN_IN_ENABLED ? (
          <div className="signin-google">
            {busy ? (
              <p className="signin-status">Signing you in…</p>
            ) : (
              /* Renders Google's own button and owns the whole Identity
                 Services lifecycle — script loading, cleanup, and React 18's
                 double-mount in StrictMode. */
              <GoogleLogin
                onSuccess={(response) => void onGoogleSuccess(response.credential)}
                onError={() => setError('Google sign-in was cancelled or failed. Please try again.')}
                theme="outline"
                size="large"
                width="280"
                text="signin_with"
                shape="rectangular"
                useOneTap={false}
              />
            )}
          </div>
        ) : (
          <form className="signin-dev" onSubmit={onDeveloperSignIn}>
            <p className="signin-note">
              Google sign-in is not configured. Set <code>VITE_GOOGLE_CLIENT_ID</code> in{' '}
              <code>web/.env.local</code> and restart the dev server. Until then, enter an email to
              sign in locally.
            </p>
            <label className="field">
              <span className="field-label">Email</span>
              <input
                type="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
              />
            </label>
            <button type="submit" className="button button-primary" disabled={busy}>
              {busy ? 'Signing in…' : 'Continue'}
            </button>
          </form>
        )}

        {error && (
          <p className="signin-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </main>
  )
}
