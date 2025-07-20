const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  openDirectoryDialog: () => ipcRenderer.invoke('dialog:openDirectory'),
  openFile: (filePath) => ipcRenderer.send('file:open', filePath),
  relaunchApp: () => ipcRenderer.send('app:relaunch'),
  getBackendConfig: () => ipcRenderer.invoke('get-backend-config'),
  onInitializationStatus: (callback) => ipcRenderer.on('initialization-status', callback),
  cancelInitialization: () => ipcRenderer.send('cancel-initialization')
});

// Listen for status requests from the main process
ipcRenderer.on('get-indexer-status', async (event, backendConfig) => {
  try {
    const { listenIp, listenPort } = backendConfig;
    const backendBaseUrl = `http://${listenIp}:${listenPort}`;
    const response = await fetch(`${backendBaseUrl}/api/indexer/status`);
    if (response.ok) {
      const data = await response.json();
      ipcRenderer.send('update-title', data);
    } else {
      // If backend is not ready or there's an error, send default values
      ipcRenderer.send('update-title', { queue_size: 0, active_threads: 0 });
    }
  } catch (error) {
    // Network error, etc.
    console.error('Failed to fetch indexer status:', error);
    ipcRenderer.send('update-title', { queue_size: 0, active_threads: 0 });
  }
});
