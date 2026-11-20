import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Keep local frontend requests on the same /api paths as production; Vite
// forwards them to the Go service while developing.
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
})