import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The study app runs on 5174 so it never collides with the product frontend
// (5173). backend settings.study_join_base_url must match this.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
  define: {
    // Injected into every log event (FS-10) and shown in the UI corner so the
    // moderator can verify all sessions ran the same build.
    __BUILD_HASH__: JSON.stringify(process.env.BUILD_HASH ?? 'dev'),
  },
})
