/**
 * Build-time configuration.
 *
 * Vite inlines `import.meta.env.VITE_*` at build time, so changing any of these
 * needs a rebuild (or a dev-server restart) — not just a page reload.
 */

/**
 * The Google OAuth **Web application** client id, ending in
 * `.apps.googleusercontent.com`.
 *
 * Set it in `web/.env.local` for development, and as a build-time environment
 * variable on Render. The same value has to be given to Django as
 * `GOOGLE_CLIENT_ID`: the server verifies that the `aud` claim of the token the
 * browser sends matches, and a mismatch is rejected as a forged token.
 */
export const GOOGLE_CLIENT_ID = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined)?.trim() ?? ''

/** Whether Google sign-in can be offered at all. */
export const GOOGLE_SIGN_IN_ENABLED = GOOGLE_CLIENT_ID.length > 0

if (import.meta.env.DEV && GOOGLE_CLIENT_ID && !GOOGLE_CLIENT_ID.endsWith('.apps.googleusercontent.com')) {
  // A common mix-up is pasting the client *secret*, or an iOS/Android client id.
  console.warn(
    '[auth] VITE_GOOGLE_CLIENT_ID does not look like a Web application client id ' +
      '(it should end in .apps.googleusercontent.com). Google sign-in will fail with ' +
      'an origin or audience error.',
  )
}
