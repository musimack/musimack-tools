/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
  readonly VITE_APP_NAME?: string;
  readonly VITE_FRONTEND_VERSION?: string;
  readonly VITE_REQUEST_TIMEOUT_MS?: string;
  readonly VITE_ENABLE_DEV_DIAGNOSTICS?: string;
  readonly VITE_BACKEND_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
