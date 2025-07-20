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

function createLoadingWindow() {
    const loadingWindow = new BrowserWindow({
        width: 500,
        height: 300,
        frame: true,
        resizable: true,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true,
        },
        center: true,
        title: '正在加载...',
    });

    loadingWindow.loadFile(path.join(__dirname, 'public', 'loading.html'));
    return loadingWindow;
}

function createMainWindow() {
    mainWindow = new BrowserWindow({
        width: 1000,
        height: 800,
        webPreferences: {
            preload: path.join(__dirname, 'preload.js'),
            nodeIntegration: false,
            contextIsolation: true,
        },
    });

    mainWindow.loadFile(path.join(__dirname, 'public', 'index.html'), { query: { v: Date.now() } });

    const config = readConfig();
    setInterval(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('get-indexer-status', { listenIp: config.listenIp, listenPort: config.listenPort });
        }
    }, 5000);
}

function startBackend(loadingWindow) {
    const scriptPath = path.join(app.getAppPath(), '..', 'start_backend.sh');
    
    backendProcess = spawn('/bin/bash', [scriptPath], {
        cwd: path.join(app.getAppPath(), '..'),
        env: { ...process.env, HOME: app.getPath('home') }
    });

    const sendStatus = (message) => {
        if (loadingWindow && !loadingWindow.isDestroyed()) {
            loadingWindow.webContents.send('initialization-status', message);
        }
    };

    backendProcess.stdout.on('data', (data) => {
        const output = data.toString();
        console.log(`Backend stdout: ${output}`);
        if (output.includes('INIT_STATUS:')) {
            sendStatus(output.replace('INIT_STATUS:', '').trim());
        }
        if (output.includes('Backend initialization complete')) {
            if (loadingWindow && !loadingWindow.isDestroyed()) {
                loadingWindow.close();
            }
            createMainWindow();
        }
    });

    backendProcess.stderr.on('data', (data) => {
        const output = data.toString();
        console.error(`Backend stderr: ${output}`);
        if (output.includes('INIT_STATUS:ERROR:')) {
            sendStatus(output.replace('INIT_STATUS:ERROR:', '').trim());
        }
    });

    backendProcess.on('close', (code) => {
        console.log(`Backend process exited with code ${code}`);
        if (code !== 0 && loadingWindow && !loadingWindow.isDestroyed()) {
            sendStatus(`后端服务异常退出，错误码: ${code}`);
        }
    });

    backendProcess.on('error', (err) => {
        console.error('Failed to start backend process.', err);
        sendStatus(`无法启动后端服务: ${err.message}`);
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

ipcMain.on('cancel-initialization', () => {
    if (backendProcess && !backendProcess.killed) {
        kill(backendProcess.pid, 'SIGKILL', (err) => {
            if (err) {
                console.error('Failed to kill backend process tree:', err);
            } else {
                console.log('Successfully killed backend process tree.');
            }
            app.quit();
        });
    } else {
        app.quit();
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
    const loadingWindow = createLoadingWindow();
    startBackend(loadingWindow);

    app.on('activate', () => {
        if (BrowserWindow.getAllWindows().length === 0) {
            if (mainWindow && !mainWindow.isDestroyed()) {
                mainWindow.show();
            } else if (loadingWindow && !loadingWindow.isDestroyed()) {
                loadingWindow.show();
            } else {
                const newLoadingWindow = createLoadingWindow();
                startBackend(newLoadingWindow);
            }
        }
    });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
  // 在macOS上，窗口关闭但应用仍在运行，确保清理
  else {
    console.log('All windows closed on macOS, backend process will continue running');
  }
});

// 统一的清理函数
function cleanupBackendProcess() {
  console.log('Cleaning up backend process...');
  if (backendProcess && !backendProcess.killed) {
    console.log('Sending SIGTERM to backend process...');
    backendProcess.kill('SIGTERM');
    
    // 给后端进程一些时间优雅退出
    const timeout = setTimeout(() => {
      if (backendProcess && !backendProcess.killed) {
        console.log('Backend still running, force killing with SIGKILL...');
        backendProcess.kill('SIGKILL');
        
        // 如果还失败，使用tree-kill
        setTimeout(() => {
          if (backendProcess && !backendProcess.killed) {
            console.log('Using tree-kill to force terminate...');
            kill(backendProcess.pid, 'SIGKILL');
          }
        }, 500);
      }
    }, 1500);
    
    // 清理timeout避免内存泄漏
    backendProcess.on('exit', () => {
      clearTimeout(timeout);
      console.log('Backend process exited');
    });
  }
}

// 确保所有退出路径都调用清理
app.on('before-quit', (event) => {
  console.log('Application is about to quit...');
  cleanupBackendProcess();
});

app.on('will-quit', () => {
  console.log('Application will quit...');
  cleanupBackendProcess();
});

app.on('quit', () => {
  console.log('Application quit complete');
});
