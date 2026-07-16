import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, process.cwd(), 'VITE_');
  const configuredProxyTarget = environment.VITE_BACKEND_PROXY_TARGET;
  const proxyTarget =
    typeof configuredProxyTarget === 'string' && configuredProxyTarget.length > 0
      ? configuredProxyTarget
      : 'http://127.0.0.1:8000';
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: { '/api': { target: proxyTarget, changeOrigin: false } },
    },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      clearMocks: true,
      restoreMocks: true,
      css: true,
    },
  };
});
