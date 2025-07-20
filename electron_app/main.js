const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const kill = require('tree-kill');

let backendProcess = null;
let mainWindow = null; // Make mainWindow accessible outside createWindow

// Function to read sa_config.cfg
function readConfig() {
  const appDataDir = path.join(app.getPath('home'), '.search_app');
  const userConfigPath = path.join(appDataDir, 'sa_config.cfg');
  const projectRootConfigPath = path.join(app.getAppPath(), '..', 'sa_config.cfg');

  let configPath = projectRootConfigPath;
  if (fs.existsSync(userConfigPath)) {
    configPath = userConfigPath;
  }

  try {
    const configContent = fs.readFileSync(configPath, 'utf8');
    const lines = configContent.split('\n');
    let listenIp = '127.0.0.1'; // Default
    let listenPort = 8233; // Default
    let inServerSection = false;

    for (const line of lines) {
      if (line.trim() === '[server]') {
        inServerSection = true;
        continue;
      }
      if (line.trim().startsWith('[') && line.trim().endsWith(']')) {
        inServerSection = false;
        continue;
      }
      if (inServerSection) {
        if (line.startsWith('LISTEN_IP')) {
          listenIp = line.split('=')[1].trim();
        } else if (line.startsWith('LISTEN_PORT')) {
          listenPort = parseInt(line.split('=')[1].trim(), 10);
        }
      }
    }
    return { listenIp, listenPort };
  } catch (error) {
    console.error('Error reading sa_config.cfg:', error);
    return { listenIp: '127.0.0.1', listenPort: 8233 }; // Fallback
  }
}

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

  // Load the index.html of the app with a cache-busting parameter.
  mainWindow.loadFile(path.join(__dirname, 'public', 'index.html'), { query: { v: Date.now() } });

  // Start polling for indexer status
  const config = readConfig();
  setInterval(() => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('get-indexer-status', { listenIp: config.listenIp, listenPort: config.listenPort });
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

// IPC Handlers - register only once at app startup
ipcMain.handle('get-backend-config', () => {
  return readConfig();
});

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

app.whenReady().then(() => {
  startBackend();
  createWindow();

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
