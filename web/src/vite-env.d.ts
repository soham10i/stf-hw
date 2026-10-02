/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "0" builds the standalone twin (no live API), see shared/mode.ts */
  readonly VITE_LIVE_API?: string;
}
