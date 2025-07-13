const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const kill = require('tree-kill');

let backendProcess = null;
let mainWindow = null; // Make mainWindow accessible outside createWindow

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1000,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // Load the index.html of the app.
  mainWindow.loadFile(path.join(__dirname, 'public', 'index.html'));

  // Start polling for indexer status
  setInterval(() => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('get-indexer-status');
    }
  }, 5000); // 5 seconds

  // Open the DevTools.
  //mainWindow.webContents.openDevTools();
}

function startBackend() {
  const scriptPath = path.join(app.getAppPath(), '..', 'start_backend.sh');
  
  backendProcess = spawn('/bin/bash', [scriptPath], {
    cwd: path.join(app.getAppPath(), '..') // Set working directory to project root
  });

  backendProcess.stdout.on('data', (data) => {
    console.log(`Backend stdout: ${data}`);
  });

  backendProcess.stderr.on('data', (data) => {
    console.error(`Backend stderr: ${data}`);
  });

  backendProcess.on('close', (code) => {
    console.log(`Backend process exited with code ${code}`);
  });
}

app.whenReady().then(() => {
  startBackend();
  createWindow();

  // IPC Handlers for directory selection and file opening
  ipcMain.handle('dialog:openDirectory', async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog({
      properties: ['openDirectory']
    });
    if (canceled) {
      return null;
    } else {
      return filePaths[0];
    }
  });

  ipcMain.on('file:open', (event, filePath) => {
    shell.openPath(filePath);
  });

  ipcMain.on('update-title', (event, { queue_size, active_threads }) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      const originalTitle = 'File Search App';
      if (queue_size > 0 || active_threads > 0) {
        mainWindow.setTitle(`${originalTitle} - 索引中 (队列: ${queue_size}, 线程: ${active_threads})`);
      } else {
        mainWindow.setTitle(originalTitle);
      }
    }
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('will-quit', () => {
  // Kill the backend process and its entire process tree when the Electron app is closing
  if (backendProcess && backendProcess.pid) {
    kill(backendProcess.pid, 'SIGKILL', (err) => {
      if (err) {
        console.error('Failed to kill backend process tree:', err);
      } else {
        console.log('Successfully killed backend process tree.');
      }
    });
  }
});
