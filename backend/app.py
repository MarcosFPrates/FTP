
from flask import Flask, jsonify, request, session, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
from ftplib import FTP, error_perm
import os
import threading
import time
from datetime import datetime

app = Flask(__name__, static_folder='../frontend', static_url_path='/')
app.secret_key = os.urandom(24)
CORS(app, supports_credentials=True)
socketio = SocketIO(app, cors_allowed_origins="*")

ftp_connections = {}
download_tasks = {}

class DownloadTask:
    def __init__(self, ftp_details, remote_path, local_path, sid):
        self.ftp_details = ftp_details
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
            ftp = FTP(self.ftp_details['server'])
            ftp.login(self.ftp_details['user'], self.ftp_details['password'])

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
            if self in download_tasks.values():
                del download_tasks[self.remote_path]


    def toggle_pause(self):
        self.is_paused = not self.is_paused

    def cancel(self):
        self.is_cancelled = True

@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/api/connect', methods=['POST'])
def connect():
    data = request.json
    server = data.get('server')
    user = data.get('user')
    password = data.get('password')

    session_id = os.urandom(16).hex()

    try:
        ftp = FTP(server)
        ftp.login(user, password)
        ftp_connections[session_id] = {'ftp': ftp, 'details': {'server': server, 'user': user, 'password': password}}
        session['session_id'] = session_id
        return jsonify({'message': 'Conectado com sucesso', 'session_id': session_id})
    except error_perm as e:
        return jsonify({'error': f'Falha na autenticação: {e}'}), 401
    except Exception as e:
        return jsonify({'error': f'Não foi possível conectar ao servidor: {e}'}), 500

@app.route('/api/list', methods=['GET'])
def list_files():
    session_id = session.get('session_id')
    if not session_id or session_id not in ftp_connections:
        return jsonify({'error': 'Não conectado'}), 401

    ftp = ftp_connections[session_id]['ftp']
    path = request.args.get('path', '/')
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')

    try:
        ftp.cwd(path)
        items = list(ftp.mlsd())

        if start_date_str and end_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            filtered_items = []
            for name, facts in items:
                try:
                    item_date = datetime.strptime(facts['modify'], '%Y%m%d%H%M%S').date()
                    if start_date <= item_date <= end_date:
                        filtered_items.append((name, facts))
                except (ValueError, KeyError):
                    continue
            items = filtered_items

        return jsonify(items)
    except Exception as e:
        return jsonify({'error': f'Falha ao listar arquivos: {e}'}), 500

@app.route('/api/download', methods=['POST'])
def download_file():
    session_id = session.get('session_id')
    if not session_id or session_id not in ftp_connections:
        return jsonify({'error': 'Não conectado'}), 401

    data = request.json
    remote_path = data.get('remote_path')
    local_path = os.path.join('downloads', os.path.basename(remote_path))
    os.makedirs('downloads', exist_ok=True)

    task = DownloadTask(ftp_connections[session_id]['details'], remote_path, local_path, request.sid)
    download_tasks[remote_path] = task
    task.start()

    return jsonify({'message': 'Download iniciado'})

@app.route('/downloads/<path:filename>')
def serve_downloaded_file(filename):
    return send_from_directory('downloads', filename, as_attachment=True)


@app.route('/api/disconnect', methods=['POST'])
def disconnect():
    session_id = session.get('session_id')
    if session_id and session_id in ftp_connections:
        ftp = ftp_connections.pop(session_id)['ftp']
        try:
            ftp.quit()
        except Exception as e:
            print(f"Erro ao desconectar: {e}")
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
