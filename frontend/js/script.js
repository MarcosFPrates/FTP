
document.addEventListener('DOMContentLoaded', () => {
    const connectBtn = document.getElementById('connect-btn');
    const serverInput = document.getElementById('server');
    const userInput = document.getElementById('user');
    const passwordInput = document.getElementById('password');
    const fileListContainer = document.getElementById('file-list-container');
    const fileListBody = document.getElementById('file-list');
    const pathBreadcrumbs = document.getElementById('path-breadcrumbs');
    const downloadsList = document.getElementById('downloads-list');
    const startDateInput = document.getElementById('start-date');
    const endDateInput = document.getElementById('end-date');
    const filterBtn = document.getElementById('filter-btn');

    let isConnected = false;
    let currentPath = '/';
    const socket = io('http://localhost:5001');

    socket.on('connect', () => console.log('Socket.IO connected'));
    socket.on('disconnect', () => console.log('Socket.IO disconnected'));

    socket.on('download_progress', (data) => {
        const progressBar = document.getElementById(`progress-${data.remote_path}`);
        if (progressBar) {
            progressBar.value = data.progress;
        }
    });

    socket.on('download_complete', (data) => {
        const downloadItem = document.getElementById(`download-${data.remote_path}`);
        if (downloadItem) {
            downloadItem.innerHTML += ` - <a href="http://localhost:5001/downloads/${data.filename}" target="_blank" class="text-blue-500">Salvar</a>`;
        }
    });

    socket.on('download_error', (data) => {
        alert(`Download error: ${data.error}`);
    });

    connectBtn.addEventListener('click', () => {
        if (isConnected) {
            disconnect();
        } else {
            connect();
        }
    });

    filterBtn.addEventListener('click', () => {
        fetchFileList(currentPath);
    });

    async function connect() {
        const server = serverInput.value;
        const user = userInput.value;
        const password = passwordInput.value;

        try {
            const response = await fetch('http://localhost:5001/api/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ server, user, password }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Connection failed');
            }

            const data = await response.json();
            isConnected = true;
            updateConnectionUI();
            currentPath = '/';
            fetchFileList(currentPath);

        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    async function disconnect() {
        try {
            await fetch('http://localhost:5001/api/disconnect', { method: 'POST' });
            isConnected = false;
            updateConnectionUI();
            fileListBody.innerHTML = '';
        } catch (error) {
            alert(`Error disconnecting: ${error.message}`);
        }
    }

    async function fetchFileList(path) {
        const startDate = startDateInput.value;
        const endDate = endDateInput.value;
        let url = `http://localhost:5001/api/list?path=${encodeURIComponent(path)}`;
        if (startDate && endDate) {
            url += `&start_date=${startDate}&end_date=${endDate}`;
        }

        try {
            const response = await fetch(url);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to list files');
            }
            const files = await response.json();
            renderFileList(files, path);
        } catch (error) {
            alert(`Error: ${error.message}`);
        }
    }

    function renderFileList(files, path) {
        fileListBody.innerHTML = '';
        pathBreadcrumbs.textContent = path;

        if (path !== '/') {
            const parentRow = document.createElement('tr');
            parentRow.innerHTML = `<td colspan="4" class="p-2 cursor-pointer hover:bg-gray-200 file-item directory">..</td>`;
            parentRow.addEventListener('click', () => {
                const parentPath = path.substring(0, path.lastIndexOf('/', path.length - 2)) + '/';
                currentPath = parentPath;
                fetchFileList(parentPath);
            });
            fileListBody.appendChild(parentRow);
        }

        files.sort((a, b) => {
            if (a[1].type === 'dir' && b[1].type !== 'dir') return -1;
            if (a[1].type !== 'dir' && b[1].type === 'dir') return 1;
            return a[0].localeCompare(b[0]);
        });

        files.forEach(([name, facts]) => {
            const row = document.createElement('tr');
            const isDirectory = facts.type === 'dir';
            const remoteFilePath = `${path}${name}`;

            row.innerHTML = `
                <td class="p-2 ${isDirectory ? 'cursor-pointer hover:bg-gray-200 file-item directory' : 'file-item file'}">${name}</td>
                <td class="p-2">${facts.size || ''}</td>
                <td class="p-2">${facts.modify ? formatDate(facts.modify) : ''}</td>
                <td class="p-2">${!isDirectory ? `<button class="download-btn bg-green-500 text-white px-2 py-1 rounded text-sm" data-remote-path="${remoteFilePath}">Download</button>` : ''}</td>
            `;

            if (isDirectory) {
                row.querySelector('td').addEventListener('click', () => {
                    currentPath = `${path}${name}/`;
                    fetchFileList(currentPath);
                });
            } else {
                row.querySelector('.download-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    startDownload(remoteFilePath);
                });
            }
            fileListBody.appendChild(row);
        });
    }

    async function startDownload(remotePath) {
        try {
            await fetch('http://localhost:5001/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ remote_path: remotePath }),
            });
            addDownloadToList(remotePath);
        } catch (error) {
            alert(`Error starting download: ${error.message}`);
        }
    }

    function addDownloadToList(remotePath) {
        const filename = remotePath.split('/').pop();
        const downloadItem = document.createElement('div');
        downloadItem.id = `download-${remotePath}`;
        downloadItem.className = 'p-2 border-b';
        downloadItem.innerHTML = `
            <span>${filename}</span>
            <progress id="progress-${remotePath}" value="0" max="100" class="w-full"></progress>
            <button class="pause-btn bg-yellow-500 text-white px-2 py-1 rounded text-sm" data-remote-path="${remotePath}">Pause</button>
            <button class="cancel-btn bg-red-500 text-white px-2 py-1 rounded text-sm" data-remote-path="${remotePath}">Cancel</button>
        `;
        downloadsList.appendChild(downloadItem);

        downloadItem.querySelector('.pause-btn').addEventListener('click', function() {
            socket.emit('pause_download', { remote_path: remotePath });
            this.textContent = this.textContent === 'Pause' ? 'Resume' : 'Pause';
        });

        downloadItem.querySelector('.cancel-btn').addEventListener('click', () => {
            socket.emit('cancel_download', { remote_path: remotePath });
            downloadItem.remove();
        });
    }

    function updateConnectionUI() {
        if (isConnected) {
            connectBtn.textContent = 'Desconectar';
            connectBtn.classList.replace('bg-blue-500', 'bg-red-500');
            connectBtn.classList.replace('hover:bg-blue-600', 'hover:bg-red-600');
            fileListContainer.classList.remove('hidden');
            serverInput.disabled = true;
            userInput.disabled = true;
            passwordInput.disabled = true;
        } else {
            connectBtn.textContent = 'Conectar';
            connectBtn.classList.replace('bg-red-500', 'bg-blue-500');
            connectBtn.classList.replace('hover:bg-red-600', 'hover:bg-blue-600');
            fileListContainer.classList.add('hidden');
            serverInput.disabled = false;
            userInput.disabled = false;
            passwordInput.disabled = false;
        }
    }

    function formatDate(dateString) {
        const year = dateString.substring(0, 4);
        const month = dateString.substring(4, 6);
        const day = dateString.substring(6, 8);
        const hour = dateString.substring(8, 10);
        const minute = dateString.substring(10, 12);
        return `${day}/${month}/${year} ${hour}:${minute}`;
    }
});
