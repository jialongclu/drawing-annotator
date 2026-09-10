/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Where Django is listening in development.
const DEFAULT_API_TARGET = 'http://127.0.0.1:8000'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_PROXY || DEFAULT_API_TARGET

  // If the app is pointed straight at Django, the proxy would only shadow it.
  const usingProxy = !env.VITE_API_BASE_URL

  return {
    plugins: [react()],
    server: {
      port: 5173,
      // Fail rather than drift. Vite's default is to hop to the next free port
      // when 5173 is taken, which silently moves the app to an origin the API
      // has not been told about — surfacing later as a CORS error that looks
      // like a server misconfiguration rather than a busy port.
      strictPort: true,
      proxy: usingProxy
        ? {
            // Same-origin in development, exactly as in production where
            // Django serves the SPA itself. No CORS, and the refresh cookie
            // stays SameSite=Strict.
            '/api': { target, changeOrigin: true },
          }
        : undefined,
    },
    build: { outDir: 'dist', sourcemap: false },
    test: {
      // Most suites are pure logic and need no DOM; the component tests opt in
      // with a `@vitest-environment jsdom` docblock.
      environment: 'node',
      globals: false,
      restoreMocks: true,
    },
  }
})
