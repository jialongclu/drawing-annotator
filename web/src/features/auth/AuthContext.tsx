import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { api } from '../../lib/api'
import type { User } from '../../types'

interface AuthValue {
  user: User | null
  status: 'loading' | 'signed-in' | 'signed-out'
  signInWithGoogle: (idToken: string) => Promise<void>
  signInAsDeveloper: (email: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [status, setStatus] = useState<AuthValue['status']>('loading')

  // On boot, trade the HttpOnly refresh cookie for an access token. This is
  // what keeps a reload from bouncing the user back to the sign-in screen.
  useEffect(() => {
    let cancelled = false
    api
      .restoreSession()
      .then((restored) => {
        if (cancelled) return
        setUser(restored)
        setStatus(restored ? 'signed-in' : 'signed-out')
      })
      .catch(() => {
        if (!cancelled) setStatus('signed-out')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const signInWithGoogle = useCallback(async (idToken: string) => {
    const signedIn = await api.signInWithGoogle(idToken)
    setUser(signedIn)
    setStatus('signed-in')
  }, [])

  const signInAsDeveloper = useCallback(async (email: string) => {
    const signedIn = await api.signInAsDeveloper(email)
    setUser(signedIn)
    setStatus('signed-in')
  }, [])

  const signOut = useCallback(async () => {
    await api.signOut()
    setUser(null)
    setStatus('signed-out')
  }, [])

  const value = useMemo(
    () => ({ user, status, signInWithGoogle, signInAsDeveloper, signOut }),
    [user, status, signInWithGoogle, signInAsDeveloper, signOut],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside an AuthProvider.')
  return value
}
