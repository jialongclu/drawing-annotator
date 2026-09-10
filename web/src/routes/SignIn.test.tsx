/**
 * @vitest-environment jsdom
 *
 * Which sign-in the card offers.
 *
 * This is the regression that prompted the change: with a client id configured
 * the user must get Google's button, not the local development form. The
 * branch is driven purely by `GOOGLE_SIGN_IN_ENABLED`, so a missing or empty
 * `VITE_GOOGLE_CLIENT_ID` is the only thing that can send it the wrong way.
 */

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const signInWithGoogle = vi.fn()
const signInAsDeveloper = vi.fn()

vi.mock('../features/auth/AuthContext', () => ({
  useAuth: () => ({ signInWithGoogle, signInAsDeveloper }),
}))

// Stand in for Google's iframe button, which cannot load in jsdom.
vi.mock('@react-oauth/google', () => ({
  GoogleLogin: (props: { onSuccess: (r: { credential?: string }) => void }) => (
    <button type="button" data-testid="google-button" onClick={() => props.onSuccess({ credential: 'tok' })}>
      Sign in with Google
    </button>
  ),
}))

const configMock = vi.hoisted(() => ({ enabled: true }))
vi.mock('../lib/config', () => ({
  get GOOGLE_SIGN_IN_ENABLED() {
    return configMock.enabled
  },
  get GOOGLE_CLIENT_ID() {
    return configMock.enabled ? 'test.apps.googleusercontent.com' : ''
  },
}))

const { SignIn } = await import('./SignIn')

afterEach(cleanup)

describe('with a Google client id configured', () => {
  beforeEach(() => {
    configMock.enabled = true
    signInWithGoogle.mockReset()
    signInWithGoogle.mockResolvedValue(undefined)
  })

  it('offers the Google button', () => {
    render(<SignIn />)

    expect(screen.getByTestId('google-button')).toBeTruthy()
  })

  it('does not offer the local development form', () => {
    render(<SignIn />)

    expect(screen.queryByLabelText('Email')).toBeNull()
    expect(screen.queryByText(/not configured/i)).toBeNull()
  })

  it('sends the credential Google returns to the API', async () => {
    render(<SignIn />)

    screen.getByTestId('google-button').click()
    await vi.waitFor(() => expect(signInWithGoogle).toHaveBeenCalledWith('tok'))
  })

  it('surfaces a failed exchange instead of failing silently', async () => {
    signInWithGoogle.mockRejectedValue(new Error('Client ids do not match'))
    render(<SignIn />)

    screen.getByTestId('google-button').click()

    await vi.waitFor(() => expect(screen.getByRole('alert').textContent).toContain('Client ids do not match'))
  })
})

describe('with no Google client id', () => {
  beforeEach(() => {
    configMock.enabled = false
  })

  it('falls back to the local development form', () => {
    render(<SignIn />)

    expect(screen.queryByTestId('google-button')).toBeNull()
    expect(screen.getByLabelText('Email')).toBeTruthy()
  })

  it('says which variable to set', () => {
    render(<SignIn />)

    expect(screen.getByText(/VITE_GOOGLE_CLIENT_ID/)).toBeTruthy()
  })
})
