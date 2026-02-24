import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  optimizeDeps: {
    exclude: ['opencascade.js'],
  },
  server: {
    fs: {
      allow: ['..'],
    },
  },
})
