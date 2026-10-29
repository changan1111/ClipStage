const { app, BrowserWindow, ipcMain, nativeImage, shell, dialog } = require('electron');
const fs = require('fs');
const path = require('path');

const cfg = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'));
const IS_WIN = process.platform === 'win32';
const SERVER_ORIGIN = new URL(cfg.serverUrl).origin;
const SERVER_HOST = new URL(cfg.serverUrl).hostname;
const SHARE_NAME = cfg.shareName || 'staging';
// Staging share as seen on THIS (editing) computer: /Volumes/staging on a Mac, the \\HOST\staging
// network path on Windows (set "stagingMount" in config.json to use a mapped drive letter instead).
const STAGING_MOUNT = cfg.stagingMount ||
  (IS_WIN ? '\\\\' + SERVER_HOST + '\\' + SHARE_NAME : '/Volumes/' + SHARE_NAME);

// 32x32 drag icon, generated in code so no extra file is needed
const ICON_B64 = 'iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAlElEQVR4nO2WMQrAIAxF09JLtIPe/1g6tNfopIOI1ORHheaNIvxnEiFEhvF3ttqhc+7WCIsxXk0BreCWyD4isEUWGPX6MmudCvQQQjinCiQJhIi4BVIR2AxwJaBDyKmGyi/oETk0BLz3z9e7UIGe4ASsBZxwIkAFuMFiAWlwgtUCVDhbAEkWqG0rWiy1kEzfCQ1jOi/ZpDcgcZsLWQAAAABJRU5ErkJggg==';
const dragIcon = nativeImage.createFromDataURL('data:image/png;base64,' + ICON_B64);

let mainWin = null;

function createWindow() {
  const win = new BrowserWindow({
    width: 1500, height: 950, title: 'ClipStage',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWin = win;
  win.loadURL(cfg.serverUrl);

  // The "Open Finder" button navigates to smb://... - hand that to the operating system instead of
  // Electron. Windows cannot open smb:// links, so they are turned into \\host\share\folder paths.
  const external = (url) => /^smb:\/\//i.test(url);
  const openSmb = (url) => {
    if (!IS_WIN) { shell.openExternal(url); return; }
    const u = new URL(url);
    const unc = '\\\\' + u.hostname + decodeURIComponent(u.pathname).replace(/\//g, '\\');
    shell.openPath(unc).then((err) => { if (err) fail('Could not open ' + unc + ': ' + err); });
  };
  win.webContents.on('will-navigate', (e, url) => {
    if (external(url)) { e.preventDefault(); openSmb(url); }
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (external(url)) { openSmb(url); return { action: 'deny' }; }
    return { action: 'allow' };
  });
}

let lastWarn = 0;
function fail(msg) {
  console.error('[ClipStage drag]', msg);
  if (Date.now() - lastWarn < 4000) return;           // don't spam popups
  lastWarn = Date.now();
  dialog.showMessageBox(mainWin, { type: 'warning', message: 'Drag to FCP failed', detail: msg });
}

// Find the staging mount on THIS computer: configured path first, then any /Volumes/staging* (Mac)
// or the \\host\share network path (Windows) that has the editor folder.
function findEditorDir(editor) {
  const cands = [STAGING_MOUNT];
  if (IS_WIN) {
    cands.push('\\\\' + SERVER_HOST + '\\' + SHARE_NAME);
  } else {
    try {
      fs.readdirSync('/Volumes').forEach((v) => {
        if (/^staging/i.test(v)) cands.push(path.join('/Volumes', v));
      });
    } catch (e) {}
  }
  for (const c of cands) {
    const dir = path.join(c, editor);
    if (fs.existsSync(dir)) return dir;
  }
  return null;
}

// Only honour drags that come from the ClipStage page itself.
ipcMain.on('clipstage-start-drag', (event, editor, filenames) => {
  try {
    const frameUrl = event.senderFrame ? event.senderFrame.url : event.sender.getURL();
    if (new URL(frameUrl).origin !== SERVER_ORIGIN) {
      return fail('Page origin ' + new URL(frameUrl).origin + ' does not match serverUrl ' + SERVER_ORIGIN + ' in config.json.');
    }
    const safe = (s) => typeof s === 'string' && s && !s.includes('/') && !s.includes('\\') && s !== '.' && s !== '..';
    const list = (Array.isArray(filenames) ? filenames : [filenames]).slice(0, 200);
    if (!safe(editor) || !list.length || !list.every(safe)) {
      return fail('Invalid editor or file name: ' + JSON.stringify([editor, list]));
    }

    const dir = findEditorDir(editor);
    if (!dir) {
      return fail('Cannot find the staging folder for "' + editor + '" under ' + STAGING_MOUNT +
        (IS_WIN ? ' or \\\\' + SERVER_HOST + '\\' + SHARE_NAME + '. Is the staging drive connected? (Run the editor setup again.)'
                : ' or any /Volumes/staging*. Is the share mounted? (Click Open Finder once.)'));
    }
    const files = list.map((f) => path.join(dir, f)).filter((f) => fs.existsSync(f));
    if (!files.length) {
      return fail('Folder found (' + dir + ') but the clip files are not in it. Refresh the staging panel.');
    }
    if (dragIcon.isEmpty()) return fail('Drag icon failed to load.');
    event.sender.startDrag({ files, file: files[0], icon: dragIcon });
  } catch (err) {
    fail('startDrag error: ' + (err && err.message ? err.message : err));
  }
});

// "Open staging folder" button (Windows editors): open the editor's folder in Explorer.
ipcMain.on('clipstage-open-staging', (event, editor) => {
  try {
    const frameUrl = event.senderFrame ? event.senderFrame.url : event.sender.getURL();
    if (new URL(frameUrl).origin !== SERVER_ORIGIN) return;
    if (typeof editor !== 'string' || !editor || /[\\/]/.test(editor) || editor === '.' || editor === '..') return;
    const dir = findEditorDir(editor);
    if (!dir) return fail('Cannot find the staging folder for "' + editor + '". Is the staging share connected?');
    shell.openPath(dir).then((err) => { if (err) fail('Could not open ' + dir + ': ' + err); });
  } catch (err) {
    fail('open staging error: ' + (err && err.message ? err.message : err));
  }
});

app.whenReady().then(createWindow);
app.on('window-all-closed', () => app.quit());
