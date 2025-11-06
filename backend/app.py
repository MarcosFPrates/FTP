
from flask import Flask, jsonify, request, session, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from ftplib import FTP, error_perm
from smb.SMBConnection import SMBConnection
from smb.smb_structs import OperationFailure
import os
import threading
import time
from datetime import datetime
import io

app = Flask(__name__, static_folder='../frontend', static_url_path='/')
app.secret_key = os.urandom(24)
CORS(app, supports_credentials=True)
socketio = SocketIO(app, cors_allowed_origins="*")

connections = {}
download_tasks = {}

class DownloadTaskFTP:
    def __init__(self, conn_details, remote_path, local_path, sid):
        self.conn_details = conn_details
        self.remote_path = remote_path
        self.local_path = local_path
        self.sid = sid
        self.is_paused = False
        self.is_cancelled = False
        self.thread = threading.Thread(target=self.run)

    def start(self):
        self.thread.start()

    def run(self):
        try:
            ftp = FTP()
            ftp.connect(self.conn_details['server'], self.conn_details['port'])
            ftp.login(self.conn_details['user'], self.conn_details['password'])

            remote_size = ftp.size(self.remote_path)
            downloaded_size = 0
            mode = 'wb'

            if os.path.exists(self.local_path):
                downloaded_size = os.path.getsize(self.local_path)
                mode = 'ab'

            with open(self.local_path, mode) as f:

                def callback(data):
                    nonlocal downloaded_size
                    f.write(data)
                    downloaded_size += len(data)
                    progress = int((downloaded_size / remote_size) * 100)
                    socketio.emit('download_progress', {'progress': progress, 'remote_path': self.remote_path}, room=self.sid)

                    while self.is_paused:
                        time.sleep(0.1)

                    if self.is_cancelled:
                        raise Exception("Download cancelado")

                ftp.retrbinary(f'RETR {self.remote_path}', callback, rest=downloaded_size if mode == 'ab' else None)

            socketio.emit('download_complete', {'path': self.local_path, 'remote_path': self.remote_path, 'filename': os.path.basename(self.local_path)}, room=self.sid)

        except Exception as e:
            socketio.emit('download_error', {'error': str(e), 'remote_path': self.remote_path}, room=self.sid)
        finally:
            ftp.quit()
            if self.remote_path in download_tasks:
                del download_tasks[self.remote_path]

    def toggle_pause(self):
        self.is_paused = not self.is_paused

    def cancel(self):
        self.is_cancelled = True

class DownloadTaskSMB:
    def __init__(self, conn_details, remote_path, local_path, sid):
        self.conn_details = conn_details
        self.remote_path = remote_path
        self.local_path = local_path
        self.sid = sid
        self.is_paused = False
        self.is_cancelled = False
        self.thread = threading.Thread(target=self.run)

    def start(self):
        self.thread.start()

    def run(self):
        try:
            conn = SMBConnection(self.conn_details['user'], self.conn_details['password'], "local_client", self.conn_details['server'], use_ntlm_v2=True)
            conn.connect(self.conn_details['server'], self.conn_details['port'])

            share, path = self.remote_path.split('/', 1)

            file_attributes, filesize = conn.getAttributes(share, path)

            downloaded_size = 0
            with open(self.local_path, 'wb') as f:

                def callback(data):
                    nonlocal downloaded_size
                    f.write(data)
                    downloaded_size += len(data)
                    progress = int((downloaded_size / filesize) * 100)
                    socketio.emit('download_progress', {'progress': progress, 'remote_path': self.remote_path}, room=self.sid)

                    while self.is_paused:
                        time.sleep(0.1)

                    if self.is_cancelled:
                        raise OperationFailure("Download cancelled by user.")


                conn.retrieveFile(share, path, f, callback=callback)


            socketio.emit('download_complete', {'path': self.local_path, 'remote_path': self.remote_path, 'filename': os.path.basename(self.local_path)}, room=self.sid)

        except Exception as e:
            socketio.emit('download_error', {'error': str(e), 'remote_path': self.remote_path}, room=self.sid)
        finally:
            conn.close()
            if self.remote_path in download_tasks:
                del download_tasks[self.remote_path]

    def toggle_pause(self):
        self.is_paused = not self.is_paused

    def cancel(self):
        self.is_cancelled = True

@app.route('/api/connect', methods=['POST'])
def connect():
    data = request.json
    server = data.get('server')
    port = int(data.get('port', 8080))
    user = data.get('user')
    password = data.get('password')
    protocol = data.get('protocol')

    session_id = os.urandom(16).hex()

    try:
        if protocol == 'ftp':
            ftp = FTP()
            ftp.connect(server, port)
            ftp.login(user, password)
            connections[session_id] = {'conn': ftp, 'protocol': 'ftp', 'details': {'server': server, 'port': port, 'user': user, 'password': password}}
            session['session_id'] = session_id
            return jsonify({'message': 'Conectado com sucesso via FTP', 'session_id': session_id})

        elif protocol == 'smb':
            conn = SMBConnection(user, password, "local_client", server, use_ntlm_v2=True)
            is_connected = conn.connect(server, port)
            if not is_connected:
                raise Exception("Não foi possível conectar ao servidor SMB")
            connections[session_id] = {'conn': conn, 'protocol': 'smb', 'details': {'server': server, 'port': port, 'user': user, 'password': password}}
            session['session_id'] = session_id
            return jsonify({'message': 'Conectado com sucesso via SMB', 'session_id': session_id})
        else:
            return jsonify({'error': 'Protocolo inválido'}), 400

    except Exception as e:
        return jsonify({'error': f'Não foi possível conectar ao servidor: {e}'}), 500


@app.route('/api/list', methods=['GET'])
def list_files():
    session_id = session.get('session_id')
    if not session_id or session_id not in connections:
        return jsonify({'error': 'Não conectado'}), 401

    conn_info = connections[session_id]
    protocol = conn_info['protocol']
    conn = conn_info['conn']
    path = request.args.get('path', '/')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    try:
        items = []
        if protocol == 'ftp':
            conn.cwd(path)
            items_raw = list(conn.mlsd())
            items = [(name, {'type': facts.get('type'), 'size': facts.get('size'), 'modify': facts.get('modify')}) for name, facts in items_raw]

        elif protocol == 'smb':
            if path == '/':
                shares = conn.listShares()
                items = [(share.name, {'type': 'dir'}) for share in shares]
            else:
                share, service_path = path.split('/', 1)
                files = conn.listPath(share, service_path)

                def format_smb_item(item):
                    is_dir = item.isDirectory
                    return (item.filename, {
                        'type': 'dir' if is_dir else 'file',
                        'size': item.file_size,
                        'modify': time.strftime('%Y%m%d%H%M%S', time.localtime(item.last_write_time))
                    })

                items = [format_smb_item(f) for f in files if f.filename not in ['.', '..']]

        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            filtered_items = []
            for name, facts in items:
                try:
                    item_date = datetime.strptime(facts['modify'], '%Y%m%d%H%M%S').date()
                    if start_date <= item_date <= end_date:
                        filtered_items.append((name, facts))
                except (ValueError, KeyError, TypeError):
                    if facts['type'] == 'dir': # Always include directories
                        filtered_items.append((name, facts))
                    continue
            items = filtered_items

        return jsonify(items)

    except OperationFailure as e:
        return jsonify({'error': f'Falha ao listar arquivos: {e}'}), 500
    except Exception as e:
        return jsonify({'error': f'Erro inesperado: {e}'}), 500


@app.route('/api/download', methods=['POST'])
def download_file():
    session_id = session.get('session_id')
    if not session_id or session_id not in connections:
        return jsonify({'error': 'Não conectado'}), 401

    conn_info = connections[session_id]
    protocol = conn_info['protocol']
    data = request.json
    remote_path = data.get('remote_path')
    local_path = os.path.join('downloads', os.path.basename(remote_path))
    os.makedirs('downloads', exist_ok=True)

    if protocol == 'ftp':
        task = DownloadTaskFTP(conn_info['details'], remote_path, local_path, session['session_id'])
    elif protocol == 'smb':
        task = DownloadTaskSMB(conn_info['details'], remote_path, local_path, session['session_id'])
    else:
        return jsonify({'error': 'Protocolo desconhecido'}), 500

    download_tasks[remote_path] = task
    task.start()
    return jsonify({'message': 'Download iniciado'})


@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    session_id = session.get('session_id')
    if session_id and session_id in connections:
        conn_info = connections.pop(session_id)
        if conn_info['protocol'] == 'ftp':
            conn_info['conn'].quit()
        elif conn_info['protocol'] == 'smb':
            conn_info['conn'].close()
        session.pop('session_id', None)
        return jsonify({'message': 'Desconectado com sucesso'})
    return jsonify({'error': 'Nenhuma sessão ativa encontrada'}), 400

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    print('Client disconnected')

@socketio.on('pause_download')
def pause_download(data):
    remote_path = data.get('remote_path')
    if remote_path in download_tasks:
        download_tasks[remote_path].toggle_pause()

@socketio.on('cancel_download')
def cancel_download(data):
    remote_path = data.get('remote_path')
    if remote_path in download_tasks:
        download_tasks[remote_path].cancel()


if __name__ == '__main__':
    socketio.run(app, debug=True, port=5001, allow_unsafe_werkzeug=True)
