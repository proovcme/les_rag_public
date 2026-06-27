// Безопасный мост: только выбор PDF-файла наружу (всё остальное — HTTP к бэкенду из renderer).
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("artel", {
  pickPdf: () => ipcRenderer.invoke("pick-pdf"),
});
