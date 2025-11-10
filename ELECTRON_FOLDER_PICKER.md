# Electron Folder Picker - Get Absolute Path with Drive Letter

This document provides a minimal example of how to get absolute folder paths (including drive letters on Windows) using Electron.

## Overview

Browser-based solutions cannot provide drive-lettered absolute paths for security reasons. Electron/desktop wrapper is the proper way to get the full absolute path programmatically.

## Implementation

### main.js (Electron main process)

```javascript
const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');

function createWindow() {
  const win = new BrowserWindow({
    width: 900,
    height: 700,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'), // recommended
      nodeIntegration: false,
      contextIsolation: true
    }
  });
  win.loadURL('http://localhost:3000'); // or loadFile
}

app.whenReady().then(createWindow);

ipcMain.handle('dialog:selectFolder', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openDirectory']
  });
  if (result.canceled) return null;
  // result.filePaths is an array of absolute paths (Windows includes drive letters)
  return result.filePaths[0] || null;
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
```

### preload.js

```javascript
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  selectFolder: () => ipcRenderer.invoke('dialog:selectFolder')
});
```

### renderer (React) - call electronAPI.selectFolder()

```javascript
import React, { useState } from 'react';

export default function FolderPickerElectron() {
  const [absPath, setAbsPath] = useState(null);

  async function pick() {
    // This requires preload exposing electronAPI.selectFolder
    const p = await window.electronAPI?.selectFolder();
    setAbsPath(p || 'No folder selected / canceled');
  }

  return (
    <div className="p-4">
      <h2 className="text-xl font-semibold mb-3">Folder picker (Electron)</h2>
      <button 
        className="px-3 py-2 bg-green-600 text-white rounded" 
        onClick={pick}
      >
        Select folder (desktop)
      </button>
      <div className="mt-3 text-sm">
        Absolute path: <code>{absPath}</code>
      </div>
      <div className="mt-2 text-xs text-gray-600">
        On Windows this will include the drive letter (e.g. C:\\data\\myfolder).
      </div>
    </div>
  );
}
```

## Notes & Recommendations

### Browser Solution
- **Easiest** but cannot provide drive-lettered absolute paths for security reasons
- Use `webkitdirectory` attribute for folder selection
- Use `webkitRelativePath` as the stored path for relative paths

### Electron / Desktop Wrapper
- **Proper way** to get the full absolute path programmatically
- Provides complete paths with drive letters on Windows
- Requires Electron app installation

### Alternative Solutions
- **Ask user to paste** the folder absolute path into an input field (for simple workflows)
- **File upload preserving folder structure**: Create a zip on client with the relative paths and send to server
- **Desktop file manager**: Use Electron and then read files from the absolute path using Node fs

## Usage Ideas

1. **For file upload preserving folder structure**: 
   - Create a zip on client with the relative paths
   - Send to server
   - Extract and process on server

2. **For a desktop file manager**: 
   - Use Electron
   - Read files from the absolute path using Node fs
   - Full file system access

## Integration with DocuSync

If you want to integrate Electron with DocuSync:

1. **Create Electron wrapper** for the FastAPI application
2. **Use Electron's dialog** to get absolute paths
3. **Send paths to FastAPI backend** via IPC or HTTP
4. **Backend validates and processes** the paths

### Example Integration

```javascript
// In Electron renderer
async function selectFolderForSync() {
  const folderPath = await window.electronAPI?.selectFolder();
  if (folderPath) {
    // Send to FastAPI backend
    const response = await fetch('http://localhost:8000/api/sync/validate-path', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token
      },
      body: JSON.stringify({ path: folderPath })
    });
    const result = await response.json();
    return result.normalized_path;
  }
  return null;
}
```

## Security Considerations

- **Context Isolation**: Always use `contextIsolation: true` for security
- **Node Integration**: Set `nodeIntegration: false` to prevent security issues
- **Preload Script**: Use preload scripts to expose only necessary APIs
- **Path Validation**: Always validate paths on the backend before processing

## References

- [Electron Dialog API](https://www.electronjs.org/docs/latest/api/dialog)
- [Electron Security](https://www.electronjs.org/docs/latest/tutorial/security)
- [Context Isolation](https://www.electronjs.org/docs/latest/tutorial/context-isolation)

