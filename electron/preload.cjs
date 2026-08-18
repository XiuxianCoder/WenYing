const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("wenying", {
  invoke: (method, params = {}) => ipcRenderer.invoke("wenying:invoke", method, params),
  dialog: (kind, options = {}) => ipcRenderer.invoke("wenying:dialog", kind, options),
  copyText: (value) => ipcRenderer.invoke("wenying:copy", value),
  openPath: (value) => ipcRenderer.invoke("wenying:open-path", value),
  revealPath: (value) => ipcRenderer.invoke("wenying:reveal-path", value),
  pathToFileUrl: (value) => ipcRenderer.invoke("wenying:file-url", value),
  platform: process.platform,
});
