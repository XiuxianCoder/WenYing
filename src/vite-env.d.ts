/// <reference types="vite/client" />

interface Window {
  wenying: {
    invoke<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T>;
    dialog(kind: string, options?: Record<string, unknown>): Promise<string | string[] | null>;
    copyText(value: string): Promise<boolean>;
    openPath(value: string): Promise<string>;
    revealPath(value: string): Promise<boolean>;
    pathToFileUrl(value: string): Promise<string>;
    platform: string;
  };
}
