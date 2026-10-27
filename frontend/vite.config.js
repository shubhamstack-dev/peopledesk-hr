import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the React app runs on :5173 and passes /api to the Python API on :8000,
// so the session cookie stays on one origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false } },
  },
  build: { chunkSizeWarningLimit: 2000 },
});
