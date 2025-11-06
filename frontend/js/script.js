
document.addEventListener('DOMContentLoaded', () => {
    const connectBtn = document.getElementById('connect-btn');
    const serverInput = document.getElementById('server');
    const portInput = document.getElementById('port');
    const userInput = document.getElementById('user');
    const passwordInput = document.getElementById('password');
    const mainContent = document.getElementById('main-content');
    const fileListBody = document.getElementById('file-list');
    const pathBreadcrumbs = document.getElementById('path-breadcrumbs');
    const downloadsList = document.getElementById('downloads-list');
    const startDateInput = document.getElementById('start-date');
    const endDateInput = document.getElementById('end-date');
    const filterBtn = document.getElementById('filter-btn');

    let isConnected = false;
    let currentPath = '/';
    const socket = io('http://localhost:5001');

    socket.on('download_progress', (data) => {
        const progressBar = document.getElementById(`progress-${data.remote_path}`);
        if (progressBar) progressBar.value = data.progress;
    });

    socket.on('download_complete', (data) => {
        const downloadItem = document.getElementById(`download-${data.remote_path}`);
        if (downloadItem) {
            const link = document.createElement('a');
            link.href = `http://localhost:5001/downloads/${data.filename}`;
            link.target = '_blank';
            link.className = 'text-indigo-400 hover:underline ml-4';
            link.textContent = 'Salvar';
            downloadItem.querySelector('.status').innerHTML = 'Completo';
            downloadItem.querySelector('.actions').innerHTML = '';
            downloadItem.querySelector('.actions').appendChild(link);
        }
    });

    socket.on('download_error', (data) => {
        showError(`Download error: ${data.error}`);
    });

    connectBtn.addEventListener('click', () => {
        if (isConnected) disconnect();
        else connect();
    });

    filterBtn.addEventListener('click', () => fetchFileList(currentPath));

    async function connect() {
        const server = serverInput.value;
        const protocol = document.querySelector('input[name="protocol"]:checked').value;
        const port = portInput.value || (protocol === 'ftp' ? '21' : '445');
        const user = userInput.value;
        const password = passwordInput.value;

        setLoading(connectBtn, true, 'Conectando...');

        try {
            const response = await fetch('http://localhost:5001/api/connect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ server, port, user, password, protocol }),
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Connection failed');
            }

            isConnected = true;
            updateConnectionUI();
            currentPath = '/';
            fetchFileList(currentPath);
        } catch (error) {
            showError(error.message);
        } finally {
            setLoading(connectBtn, false, '<i class="fas fa-plug mr-2"></i>Conectar');
        }
    }

    async function disconnect() {
        setLoading(connectBtn, true, 'Desconectando...');
        try {
            await fetch('http://localhost:5001/api/disconnect', { method: 'POST' });
            isConnected = false;
            updateConnectionUI();
            fileListBody.innerHTML = '';
        } catch (error) {
            showError(error.message);
        } finally {
            setLoading(connectBtn, false, '<i class="fas fa-plug mr-2"></i>Conectar');
        }
    }

    async function fetchFileList(path) {
        fileListBody.innerHTML = '<tr><td colspan="4" class="p-4 text-center text-gray-400">Carregando...</td></tr>';
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
            showError(error.message);
            fileListBody.innerHTML = '<tr><td colspan="4" class="p-4 text-center text-red-400">Falha ao carregar arquivos.</td></tr>';
        }
    }

    function renderFileList(files, path) {
        fileListBody.innerHTML = '';
        pathBreadcrumbs.textContent = path;

        if (path !== '/') {
            const parentRow = document.createElement('tr');
            parentRow.className = 'cursor-pointer hover:bg-gray-700';
            parentRow.innerHTML = `<td colspan="4" class="p-2 file-item directory">..</td>`;
            parentRow.addEventListener('click', () => {
                const parentPath = path.split('/').slice(0, -2).join('/') + '/';
                currentPath = parentPath || '/';
                fetchFileList(currentPath);
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
            row.className = 'border-b border-gray-700 hover:bg-gray-700';
            const isDirectory = facts.type === 'dir';
            const remoteFilePath = `${path}${name}`;

            row.innerHTML = `
                <td class="p-2 ${isDirectory ? 'cursor-pointer file-item directory' : 'file-item file'}">${name}</td>
                <td class="p-2 text-gray-400">${facts.size ? formatBytes(facts.size) : ''}</td>
                <td class="p-2 text-gray-400">${facts.modify ? formatDate(facts.modify) : ''}</td>
                <td class="p-2 text-center">${!isDirectory ? `<button class="action-btn download-btn text-indigo-400" data-remote-path="${remoteFilePath}"><i class="fas fa-download"></i></button>` : ''}</td>
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
            showError(`Error starting download: ${error.message}`);
        }
    }

    function addDownloadToList(remotePath) {
        const filename = remotePath.split('/').pop();
        const downloadItem = document.createElement('div');
        downloadItem.id = `download-${remotePath}`;
        downloadItem.className = 'download-item p-2 rounded';
        downloadItem.innerHTML = `
            <div class="flex items-center justify-between">
                <span class="truncate text-sm">${filename}</span>
                <span class="status text-sm text-gray-400">Em progresso...</span>
            </div>
            <progress id="progress-${remotePath}" value="0" max="100" class="w-full mt-1"></progress>
            <div class="actions text-right mt-1">
                <button class="action-btn pause-btn" data-remote-path="${remotePath}"><i class="fas fa-pause"></i></button>
                <button class="action-btn cancel-btn" data-remote-path="${remotePath}"><i class="fas fa-times"></i></button>
            </div>
        `;
        downloadsList.appendChild(downloadItem);

        downloadItem.querySelector('.pause-btn').addEventListener('click', function() {
            socket.emit('pause_download', { remote_path: remotePath });
            const icon = this.querySelector('i');
            icon.classList.toggle('fa-pause');
            icon.classList.toggle('fa-play');
        });

        downloadItem.querySelector('.cancel-btn').addEventListener('click', () => {
            socket.emit('cancel_download', { remote_path: remotePath });
            downloadItem.remove();
        });
    }

    function updateConnectionUI() {
        const protocolRadios = document.querySelectorAll('input[name="protocol"]');
        if (isConnected) {
            connectBtn.innerHTML = '<i class="fas fa-times mr-2"></i>Desconectar';
            connectBtn.classList.replace('bg-indigo-600', 'bg-red-600');
            connectBtn.classList.replace('hover:bg-indigo-700', 'hover:bg-red-700');
            mainContent.classList.remove('hidden');
            [serverInput, portInput, userInput, passwordInput].forEach(el => el.disabled = true);
            protocolRadios.forEach(radio => radio.disabled = true);
        } else {
            connectBtn.innerHTML = '<i class="fas fa-plug mr-2"></i>Conectar';
            connectBtn.classList.replace('bg-red-600', 'bg-indigo-600');
            connectBtn.classList.replace('hover:bg-red-700', 'hover:bg-indigo-700');
            mainContent.classList.add('hidden');
            [serverInput, portInput, userInput, passwordInput].forEach(el => el.disabled = false);
            protocolRadios.forEach(radio => radio.disabled = false);
        }
    }

    function setLoading(button, isLoading, text) {
        button.disabled = isLoading;
        button.innerHTML = isLoading ? `<i class="fas fa-spinner fa-spin mr-2"></i>${text}` : text;
    }

    function showError(message) {
        // This could be improved with a toast notification library
        console.error(message);
        alert(message);
    }

    function formatBytes(bytes, decimals = 2) {
        if (bytes == 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    function formatDate(dateString) {
        try {
            const year = dateString.substring(0, 4);
            const month = dateString.substring(4, 6);
            const day = dateString.substring(6, 8);
            const hour = dateString.substring(8, 10);
            const minute = dateString.substring(10, 12);
            return `${day}/${month}/${year} ${hour}:${minute}`;
        } catch (e) {
            return 'N/A';
        }
    }
});
