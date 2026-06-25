import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'react-vendor',
              test: /node_modules[\\/](react|react-dom|scheduler)/,
              priority: 20,
            },
            {
              name: 'charts-vendor',
              test: /node_modules[\\/](recharts|d3-|victory-vendor)/,
              priority: 30,
            },
            {
              name: 'vendor',
              test: /node_modules/,
              minSize: 20000,
              priority: 10,
            },
          ],
        },
      },
    },
  },
})
