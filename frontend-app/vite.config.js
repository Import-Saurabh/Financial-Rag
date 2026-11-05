import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:5000',
      '/query': 'http://127.0.0.1:5000',
      '/v1': 'http://127.0.0.1:5000',
      '/health': 'http://127.0.0.1:5000',
      '/providers': 'http://127.0.0.1:5000',
      '/admin': 'http://127.0.0.1:5000'
    }
  }
})
