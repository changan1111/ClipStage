const { contextBridge, ipcRenderer } = require('electron');

// Exposes two tiny functions to the ClipStage page.
contextBridge.exposeInMainWorld('clipstageNative', {
  startDrag: (editor, filename) => ipcRenderer.send('clipstage-start-drag', editor, filename),
  openStaging: (editor) => ipcRenderer.send('clipstage-open-staging', editor),
});
