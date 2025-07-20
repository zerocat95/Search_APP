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

function createInitializationWindow() {
  const initWindow = new BrowserWindow({
    width: 500,
    height: 400,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    center: true,
  });

  initWindow.loadFile(path.join(__dirname, 'public', 'initialization.html'));
  return initWindow;
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

async function checkAndInitializePythonEnv() {
  const venvPath = path.join(app.getPath('home'), '.search_app', '.venv');
  const requirementsPath = path.join(app.getAppPath(), '..', 'requirements.txt');
  const initScriptPath = path.join(app.getAppPath(), '..', 'init_python_env.sh');

  if (!fs.existsSync(venvPath)) {
    console.log('Python虚拟环境不存在，开始初始化...');
    
    // 发送初始化状态给前端
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('env-initialization-start');
    }

    return new Promise((resolve, reject) => {
      const initProcess = spawn('/bin/bash', [initScriptPath, requirementsPath], {
        cwd: path.join(app.getAppPath(), '..')
      });

      initProcess.stdout.on('data', (data) => {
        console.log(`Init stdout: ${data}`);
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('env-initialization-progress', data.toString());
        }
      });

      initProcess.stderr.on('data', (data) => {
        console.error(`Init stderr: ${data}`);
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('env-initialization-progress', data.toString());
        }
      });

      initProcess.on('close', (code) => {
        if (code === 0) {
          console.log('Python环境初始化完成');
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('env-initialization-complete');
          }
          resolve();
        } else {
          console.error(`Python环境初始化失败，退出码: ${code}`);
          if (mainWindow && !mainWindow.isDestroyed()) {
            mainWindow.webContents.send('env-initialization-error', `初始化失败，退出码: ${code}`);
          }
          reject(new Error(`Python环境初始化失败`));
        }
      });
    });
  } else {
    console.log('Python虚拟环境已存在');
    return Promise.resolve();
  }
}

function startBackend() {
  const venvPath = path.join(app.getPath('home'), '.search_app', '.venv');
  const scriptPath = path.join(venvPath, 'bin', 'python');
  const mainPyPath = path.join(app.getAppPath(), '..', 'main.py');
  
  // 使用虚拟环境中的Python运行main.py
  backendProcess = spawn(scriptPath, [mainPyPath], {
    cwd: path.join(app.getAppPath(), '..')
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

app.whenReady().then(async () => {
  const venvPath = path.join(app.getPath('home'), '.search_app', '.venv');
  
  if (!fs.existsSync(venvPath)) {
    // 显示初始化窗口
    const initWindow = createInitializationWindow();
    
    try {
      await checkAndInitializePythonEnv();
      initWindow.close();
      startBackend();
      createMainWindow();
    } catch (error) {
      console.error('初始化失败:', error);
      initWindow.webContents.send('env-initialization-error', error.message);
    }
  } else {
    startBackend();
    createMainWindow();
  }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createMainWindow();
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
