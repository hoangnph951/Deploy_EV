/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly GOONG_MAPTILES_KEY?: string;
  readonly VITE_GOONG_MAPTILES_KEY?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
