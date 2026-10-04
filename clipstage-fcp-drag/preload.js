const { contextBridge, ipcRenderer } = require('electron');

// Exposes one tiny function to the ClipStage page.
contextBridge.exposeInMainWorld('clipstageNative', {
  startDrag: (editor, filename) => ipcRenderer.send('clipstage-start-drag', editor, filename),
});
