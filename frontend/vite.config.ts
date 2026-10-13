import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // In development the API runs on :8000; going through this proxy keeps everything same-origin,
    // which the session cookie and CSRF protection rely on.
    // changeOrigin stays false so Django sees the browser's Host and its CSRF origin check passes.
    proxy: { '/api': { target: process.env.API_PROXY ?? 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    exclude: ['e2e/**', 'node_modules/**'],
    env: { VITE_API_URL: 'http://localhost' },
  },
})
