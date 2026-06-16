// АРТЕЛЬ Фабрика семейств — главный процесс Electron.
// Морда общается с локальным бэкендом (127.0.0.1:5057) из renderer по HTTP.
const { app, BrowserWindow, ipcMain, dialog } = require("electron");

function createWindow() {
  const win = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 900,
    minHeight: 600,
    title: "АРТЕЛЬ Фабрика семейств",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: require("path").join(__dirname, "preload.js"),
    },
  });
  win.loadFile("index.html");
}

// Диалог выбора PDF-технички (путь нужен бэкенду для извлечения).
ipcMain.handle("pick-pdf", async () => {
  const res = await dialog.showOpenDialog({
    title: "Выберите техничку (PDF)",
    filters: [{ name: "PDF", extensions: ["pdf"] }],
    properties: ["openFile"],
  });
  return res.canceled ? null : res.filePaths[0];
});

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
