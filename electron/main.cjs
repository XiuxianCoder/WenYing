const { app, BrowserWindow, clipboard, dialog, ipcMain, nativeImage, shell } = require("electron");
const fs = require("node:fs");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { PythonBridge } = require("./python-bridge-client.cjs");

const isDevelopment = Boolean(process.env.WENYING_DEV_URL);
const projectRoot = path.resolve(__dirname, "..");
let mainWindow = null;
let bridge = null;

function iconPath() {
  // `npm run start` is a production renderer running from the source tree, not a
  // packaged application.  Use app.isPackaged here so that this mode still gets
  // WenYing's icon instead of Electron's default atom icon.
  return app.isPackaged
    ? path.join(process.resourcesPath, "data", "wenying.ico")
    : path.join(projectRoot, "data", "wenying.ico");
}

function createWindow() {
  console.log(`Creating WenYing window (${isDevelopment ? "development" : "production"})`);
  mainWindow = new BrowserWindow({
    title: "文映 WenYing",
    width: 1540,
    height: 960,
    minWidth: 1180,
    minHeight: 760,
    show: false,
    backgroundColor: "#f3efe6",
    icon: nativeImage.createFromPath(iconPath()),
    titleBarStyle: "hidden",
    titleBarOverlay: {
      color: "#f3efe6",
      symbolColor: "#284940",
      height: 42,
    },
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://") || url.startsWith("http://")) shell.openExternal(url);
    return { action: "deny" };
  });
  mainWindow.webContents.on("console-message", (details) => {
    if (details.level === "error" || details.level === "warning") {
      console.error(`[Renderer ${details.level}] ${details.message}`);
    }
  });
  mainWindow.webContents.on("render-process-gone", (_event, details) => {
    console.error("Renderer process stopped:", details.reason, details.exitCode);
  });
  mainWindow.webContents.on("did-fail-load", (_event, code, description, url) => {
    console.error("Renderer failed to load:", code, description, url);
  });
  mainWindow.webContents.on("did-finish-load", () => console.log("Renderer finished loading"));
  mainWindow.webContents.on("will-navigate", (event, url) => {
    const allowed = isDevelopment ? process.env.WENYING_DEV_URL : pathToFileURL(path.join(projectRoot, "dist", "index.html")).href;
    if (!url.startsWith(allowed)) event.preventDefault();
  });
  mainWindow.once("ready-to-show", () => {
    mainWindow.show();
    mainWindow.focus();
    if (process.env.WENYING_CAPTURE_UI) {
      setTimeout(async () => {
        try {
          const image = await mainWindow.capturePage();
          const output = path.join(projectRoot, "output", "electron-ui-check.png");
          fs.mkdirSync(path.dirname(output), { recursive: true });
          fs.writeFileSync(output, image.toPNG());
          console.log(`UI capture saved: ${output}`);
        } catch (error) {
          console.error("UI capture failed:", error);
        }
      }, 1200);
    }
  });
  mainWindow.on("close", () => console.log("Main window closing"));
  mainWindow.on("closed", () => { console.log("Main window closed"); mainWindow = null; });

  if (isDevelopment) mainWindow.loadURL(process.env.WENYING_DEV_URL);
  else mainWindow.loadFile(path.join(projectRoot, "dist", "index.html"));
}

function dialogOptions(kind, options) {
  const base = { properties: ["openFile"] };
  if (kind === "word") return { ...base, title: "选择 Word 原稿", filters: [{ name: "Word 文档", extensions: ["docx"] }] };
  if (kind === "images") return { ...base, title: "选择正文图片", properties: ["openFile", "multiSelections"], filters: [{ name: "图片", extensions: ["png", "jpg", "jpeg", "webp", "gif"] }] };
  if (kind === "template-images") return { ...base, title: "选择模板截图", properties: ["openFile", "multiSelections"], filters: [{ name: "图片", extensions: ["png", "jpg", "jpeg", "webp"] }] };
  if (kind === "html") return { ...base, title: "选择已有 HTML", filters: [{ name: "HTML", extensions: ["html", "htm"] }] };
  if (kind === "cover") return { ...base, title: "选择封面", filters: [{ name: "图片", extensions: ["png", "jpg", "jpeg", "webp"] }] };
  if (kind === "output-directory") return { title: "选择输出目录", properties: ["openDirectory", "createDirectory"] };
  return { ...base, ...options };
}

function registerIpc() {
  ipcMain.handle("wenying:invoke", async (_event, method, params) => bridge.invoke(method, params || {}));
  ipcMain.handle("wenying:dialog", async (_event, kind, options) => {
    if (kind === "save-html") {
      const result = await dialog.showSaveDialog(mainWindow, {
        title: "导出 HTML",
        defaultPath: options?.defaultPath || "文映文章.html",
        filters: [{ name: "HTML 文件", extensions: ["html"] }],
      });
      return result.canceled ? null : result.filePath;
    }
    const result = await dialog.showOpenDialog(mainWindow, dialogOptions(kind, options));
    if (result.canceled) return kind === "images" || kind === "template-images" ? [] : null;
    return kind === "images" || kind === "template-images" ? result.filePaths : result.filePaths[0] || null;
  });
  ipcMain.handle("wenying:copy", (_event, value) => { clipboard.writeText(String(value || "")); return true; });
  ipcMain.handle("wenying:open-path", async (_event, value) => shell.openPath(String(value || "")));
  ipcMain.handle("wenying:reveal-path", (_event, value) => { shell.showItemInFolder(String(value || "")); return true; });
  ipcMain.handle("wenying:file-url", (_event, value) => pathToFileURL(String(value || "")).href);
}

const singleInstance = app.requestSingleInstanceLock();
if (!singleInstance) app.quit();
else {
  if (process.platform === "win32") app.setAppUserModelId("com.wenying.desktop");
  app.on("second-instance", () => {
    if (!mainWindow) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.show();
    mainWindow.focus();
  });
  app.whenReady().then(() => {
    const packagedRoot = app.isPackaged ? process.resourcesPath : null;
    bridge = new PythonBridge(projectRoot, packagedRoot, app.isPackaged ? app.getPath("userData") : projectRoot);
    registerIpc();
    createWindow();
  });
  app.on("window-all-closed", () => { console.log("All windows closed"); app.quit(); });
  app.on("before-quit", () => { console.log("Application quitting"); bridge?.stop(); });
}
