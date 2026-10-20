import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

declare const process: { env: Record<string, string | undefined> }

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // SERUEN_API=http://localhost:8001 npm run dev — другой бэкенд для проверки
      '/api': { target: process.env.SERUEN_API ?? 'http://localhost:8000', changeOrigin: true },
    },
  },
})
