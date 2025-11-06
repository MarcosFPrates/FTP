
import sys
import os
from ftplib import FTP, error_perm
from datetime import datetime
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTreeView,
    QStatusBar,
    QMessageBox,
    QFileDialog,
    QProgressBar,
    QDateEdit,
    QLabel,
)
from PyQt5.QtGui import QStandardItemModel, QStandardItem
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QDate

class DownloadThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, server, user, password, remote_path, local_path, parent=None):
        super().__init__(parent)
        self.server = server
        self.user = user
        self.password = password
        self.remote_path = remote_path
        self.local_path = local_path

        self.is_paused = False
        self.is_cancelled = False
        self.downloaded_size = 0

    def run(self):
        try:
            self.ftp = FTP(self.server)
            self.ftp.login(self.user, self.password)

            remote_size = self.ftp.size(self.remote_path)

            mode = 'wb'
            if os.path.exists(self.local_path):
                self.downloaded_size = os.path.getsize(self.local_path)
                mode = 'ab'

            if self.downloaded_size >= remote_size and remote_size > 0:
                self.finished.emit(f"O arquivo '{os.path.basename(self.local_path)}' já foi baixado.")
                return

            with open(self.local_path, mode) as f:

                def callback(data):
                    f.write(data)
                    self.downloaded_size += len(data)
                    progress = int((self.downloaded_size / remote_size) * 100)
                    self.progress.emit(progress)

                    while self.is_paused:
                        self.msleep(100)

                    if self.is_cancelled:
                        raise Exception("Download cancelado")

                self.ftp.retrbinary(f'RETR {self.remote_path}', callback, rest=self.downloaded_size if mode == 'ab' else None)

            self.finished.emit(f"Arquivo '{os.path.basename(self.local_path)}' baixado com sucesso.")

        except Exception as e:
            self.error.emit(str(e))
        finally:
            if hasattr(self, 'ftp'):
                self.ftp.quit()

    def toggle_pause(self):
        self.is_paused = not self.is_paused

    def cancel(self):
        self.is_cancelled = True

class FTPClient(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FTP Client")
        self.setGeometry(100, 100, 800, 600)

        self.ftp = None
        self.is_connected = False
        self.current_path = "/"
        self.download_thread = None

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # Connection widgets
        self.connection_layout = QHBoxLayout()
        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("Servidor FTP")
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("Usuário")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Senha")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.connect_button = QPushButton("Conectar")
        self.connect_button.clicked.connect(self.toggle_connection)
        self.connection_layout.addWidget(self.server_input)
        self.connection_layout.addWidget(self.user_input)
        self.connection_layout.addWidget(self.password_input)
        self.connection_layout.addWidget(self.connect_button)
        self.main_layout.addLayout(self.connection_layout)

        # Date filter widgets
        self.filter_layout = QHBoxLayout()
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDate(QDate.currentDate().addYears(-1))
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDate(QDate.currentDate())
        self.apply_filter_button = QPushButton("Aplicar Filtro")
        self.apply_filter_button.clicked.connect(self.populate_file_list)
        self.clear_filter_button = QPushButton("Limpar Filtro")
        self.clear_filter_button.clicked.connect(self.clear_filter)

        self.filter_layout.addWidget(QLabel("De:"))
        self.filter_layout.addWidget(self.start_date_edit)
        self.filter_layout.addWidget(QLabel("Até:"))
        self.filter_layout.addWidget(self.end_date_edit)
        self.filter_layout.addWidget(self.apply_filter_button)
        self.filter_layout.addWidget(self.clear_filter_button)
        self.main_layout.addLayout(self.filter_layout)


        # Remote file list
        self.remote_files_tree = QTreeView()
        self.file_model = QStandardItemModel()
        self.remote_files_tree.setModel(self.file_model)
        self.remote_files_tree.doubleClicked.connect(self.on_item_double_clicked)
        self.main_layout.addWidget(self.remote_files_tree)

        # Download control widgets
        self.download_controls_layout = QHBoxLayout()
        self.download_button = QPushButton("Download")
        self.download_button.clicked.connect(self.download_selected_file)
        self.pause_button = QPushButton("Pausar")
        self.pause_button.clicked.connect(self.toggle_pause_download)
        self.pause_button.setEnabled(False)
        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(self.cancel_download)
        self.cancel_button.setEnabled(False)
        self.download_controls_layout.addWidget(self.download_button)
        self.download_controls_layout.addWidget(self.pause_button)
        self.download_controls_layout.addWidget(self.cancel_button)
        self.main_layout.addLayout(self.download_controls_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.main_layout.addWidget(self.progress_bar)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Desconectado")

    def toggle_connection(self):
        if self.is_connected:
            self.disconnect_from_ftp()
        else:
            self.connect_to_ftp()

    def connect_to_ftp(self):
        server = self.server_input.text()
        user = self.user_input.text()
        password = self.password_input.text()

        if not server:
            QMessageBox.warning(self, "Aviso", "Por favor, insira o endereço do servidor FTP.")
            return

        try:
            self.ftp = FTP(server)
            self.ftp.login(user, password)
            self.is_connected = True
            self.status_bar.showMessage(f"Conectado a {server}")
            self.connect_button.setText("Desconectar")
            self.server_input.setEnabled(False)
            self.user_input.setEnabled(False)
            self.password_input.setEnabled(False)
            self.populate_file_list()
        except error_perm as e:
            QMessageBox.critical(self, "Erro de Conexão", f"Falha na autenticação: {e}")
            self.ftp = None
        except Exception as e:
            QMessageBox.critical(self, "Erro de Conexão", f"Não foi possível conectar ao servidor: {e}")
            self.ftp = None

    def disconnect_from_ftp(self):
        if self.download_thread and self.download_thread.isRunning():
            self.cancel_download()

        if self.ftp:
            try:
                self.ftp.quit()
            except Exception as e:
                print(f"Erro ao desconectar: {e}")
        self.ftp = None
        self.is_connected = False
        self.status_bar.showMessage("Desconectado")
        self.connect_button.setText("Conectar")
        self.server_input.setEnabled(True)
        self.user_input.setEnabled(True)
        self.password_input.setEnabled(True)
        self.file_model.clear()

    def populate_file_list(self):
        if not self.is_connected:
            return

        self.file_model.clear()
        self.file_model.setHorizontalHeaderLabels(['Nome', 'Tamanho', 'Data de Modificação'])

        if self.current_path != "/":
            parent_item = QStandardItem("..")
            parent_item.setData("parent", Qt.UserRole)
            self.file_model.appendRow(parent_item)

        try:
            items = list(self.ftp.mlsd())
            items.sort(key=lambda x: x[1].get('type') != 'dir')
            start_date = self.start_date_edit.date().toPyDate()
            end_date = self.end_date_edit.date().toPyDate()

            for name, facts in items:

                item_date_str = facts.get('modify', '')

                try:
                    item_date = datetime.strptime(item_date_str, "%Y%m%d%H%M%S").date()
                    if not (start_date <= item_date <= end_date):
                        continue
                except ValueError:
                    # Ignore files with invalid date format
                    pass

                item = QStandardItem(name)
                if facts['type'] == 'dir':
                    item.setData('dir', Qt.UserRole)
                else:
                    item.setData('file', Qt.UserRole)

                size_item = QStandardItem(facts.get('size', 'N/A'))
                date_item = QStandardItem(item_date_str)

                self.file_model.appendRow([item, size_item, date_item])
        except Exception as e:
            QMessageBox.critical(self, "Erro", f"Falha ao listar arquivos: {e}")

    def clear_filter(self):
        self.start_date_edit.setDate(QDate.currentDate().addYears(-10))
        self.end_date_edit.setDate(QDate.currentDate())
        self.populate_file_list()

    def on_item_double_clicked(self, index):
        item = self.file_model.itemFromIndex(index)
        item_type = item.data(Qt.UserRole)

        if item_type == 'dir':
            self.current_path += item.text() + "/"
            self.ftp.cwd(item.text())
            self.populate_file_list()
        elif item_type == "parent":
            self.current_path = "/".join(self.current_path.split("/")[:-2]) + "/"
            self.ftp.cwd("..")
            self.populate_file_list()

    def download_selected_file(self):
        selected_indexes = self.remote_files_tree.selectedIndexes()
        if not selected_indexes:
            QMessageBox.warning(self, "Aviso", "Por favor, selecione um arquivo para baixar.")
            return

        selected_index = selected_indexes[0]
        item = self.file_model.itemFromIndex(selected_index)
        item_type = item.data(Qt.UserRole)

        if item_type != 'file':
            QMessageBox.warning(self, "Aviso", "Por favor, selecione um arquivo, não uma pasta.")
            return

        filename = item.text()
        local_filepath, _ = QFileDialog.getSaveFileName(self, "Salvar Arquivo", filename)

        if not local_filepath:
            return

        self.progress_bar.setValue(0)
        self.download_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.cancel_button.setEnabled(True)

        self.download_thread = DownloadThread(
            self.server_input.text(),
            self.user_input.text(),
            self.password_input.text(),
            self.current_path + filename,
            local_filepath
        )
        self.download_thread.progress.connect(self.progress_bar.setValue)
        self.download_thread.finished.connect(self.on_download_finished)
        self.download_thread.error.connect(self.on_download_error)
        self.download_thread.start()

    def toggle_pause_download(self):
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.toggle_pause()
            self.pause_button.setText("Retomar" if self.download_thread.is_paused else "Pausar")

    def cancel_download(self):
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.cancel()

    def on_download_finished(self, message):
        QMessageBox.information(self, "Download Concluído", message)
        self.reset_download_controls()

    def on_download_error(self, error):
        if "Download cancelado" not in error:
            QMessageBox.critical(self, "Erro de Download", f"Falha ao baixar o arquivo: {error}")
        self.reset_download_controls()

    def reset_download_controls(self):
        self.download_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.pause_button.setText("Pausar")
        self.cancel_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.download_thread = None

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FTPClient()
    window.show()
    sys.exit(app.exec_())
