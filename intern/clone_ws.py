import os, sys, subprocess, time

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox

proto_py_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "external",
    "rqtll_api",
    "py",
)
if proto_py_path not in sys.path:
    sys.path.insert(0, proto_py_path)

import clone_ws_pb2
import clone_ws_pb2_grpc


class CloneWorkspaceThread(QThread):
    progress_received = Signal(str, float)
    finished_received = Signal(bool, str)

    def __init__(self, stub, request):
        super().__init__()
        self.stub = stub
        self.request = request
        self.call = None
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True
        if self.call:
            try:
                self.call.cancel()
            except Exception:
                pass

    def run(self):
        try:
            self.call = self.stub.CloneWorkspace(self.request)
            for response in self.call:
                if self._is_cancelled:
                    return
                self.progress_received.emit(response.log_line, response.progress)
                if response.completed:
                    self.finished_received.emit(response.success, response.log_line)
                    return

            if not self._is_cancelled:
                self.finished_received.emit(False, "Bad Backend")
        except Exception as exc:
            if not self._is_cancelled:
                self.progress_received.emit(f"Error de RPC: {exc}", 0.0)
                self.finished_received.emit(False, str(exc))


class CloneWorkspaceController(QObject):
    def __init__(self, root_controller):
        super().__init__()
        self.root = root_controller
        self.window = None
        self.clone_stub = clone_ws_pb2_grpc.CloneWorkspaceServiceStub(self.root.channel)
        self.clone_thread = None
        self.last_notify_time = 0.0

    def bind(self, window):
        self.window = window
        self.window.closeEvent = self._handle_close_event

        try:
            self.window.ui.BTNClone.clicked.disconnect()
        except Exception:
            pass
        self.window.ui.BTNClone.clicked.connect(self.clone_workspace)
        try:
            self.window.ui.BTNDir.clicked.disconnect()
        except Exception:
            pass
        self.window.ui.BTNDir.clicked.connect(self.select_destination_dir)

        try:
            self.window.ui.EDITUri.textChanged.disconnect()
        except Exception:
            pass
        self.window.ui.EDITUri.textChanged.connect(self._update_clone_button_state)
        self._update_clone_button_state()

    def set_current_target_dir(self, path):
        normalized = os.path.expanduser(path.strip()) if path else ""
        if not normalized:
            return False, "Ruta vacía"

        try:
            request = clone_ws_pb2.SetCurrentTargetDirRequest(target_dir=normalized)
            response = self.clone_stub.SetCurrentTargetDir(request)
            return bool(response.ok), response.message
        except Exception as exc:
            return False, str(exc)

    def _update_clone_button_state(self):
        if self.window is None:
            return

        has_url = bool(self.window.ui.EDITUri.text().strip())
        is_busy = self.clone_thread is not None and self.clone_thread.isRunning()
        self.window.ui.BTNClone.setEnabled(has_url and not is_busy)

        if has_url:
            self.window.ui.BTNClone.setToolTip("")
        else:
            self.window.ui.BTNClone.setToolTip("Ingresa la URL del proyecto a clonar")

    def select_destination_dir(self):
        if self.window is None:
            return

        current_value = self.window.ui.EDITDir.text().strip()
        base_dir = os.path.expanduser(current_value) if current_value else os.path.expanduser("~")

        chosen_dir = QFileDialog.getExistingDirectory(
            self.window,
            "Selecciona el directorio de destino",
            base_dir,
        )
        if not chosen_dir:
            return

        self.window.ui.EDITDir.setText(os.path.normpath(chosen_dir))

    def clone_workspace(self):
        if self.window is None:
            return

        repo_url = self.window.ui.EDITUri.text().strip()
        if not repo_url:
            return

        destination_dir = self.window.ui.EDITDir.text().strip()
        workspace_name = self.window.ui.EDITName.text().strip()

        request = clone_ws_pb2.CloneWorkspaceRequest(
            repository_url=repo_url,
            destination_dir=os.path.expanduser(destination_dir) if destination_dir else "",
            workspace_name=workspace_name,
            branch="",
            depth=0,
        )

        if self.clone_thread is not None and self.clone_thread.isRunning():
            return

        self.clone_thread = CloneWorkspaceThread(self.clone_stub, request)
        self.clone_thread.progress_received.connect(self._on_clone_progress)
        self.clone_thread.finished_received.connect(self._on_clone_finished)
        self._set_busy(True)
        
        self._send_notification(
            "RQTLL Clonador",
            "Iniciando clonación de repositorio...",
            icon="dialog-information",
            force=True
        )
        
        self.clone_thread.start()

    def _handle_close_event(self, event):
        if self.clone_thread and self.clone_thread.isRunning():
            self.clone_thread.cancel()
            self.clone_thread.wait()
        event.accept()

    def _set_busy(self, busy):
        if self.window is None:
            return

        self.window.ui.BTNClone.setEnabled(not busy and bool(self.window.ui.EDITUri.text().strip()))
        self.window.ui.BTNCancell.setEnabled(not busy)
        self.window.ui.BTNDir.setEnabled(not busy)
        self.window.ui.EDITUri.setEnabled(not busy)
        self.window.ui.EDITDir.setEnabled(not busy)
        self.window.ui.EDITName.setEnabled(not busy)

    def _send_notification(self, title, msg, icon="dialog-information", progress=None, force=False):
        now = time.time()
        if not force and progress is not None:
            if now - self.last_notify_time < 0.5:
                return
        self.last_notify_time = now

        cmd = ['notify-send', '--app-name', 'RQTLL IDE', '--print-id', '--icon', icon, title, msg]
        if progress is not None:
            cmd.extend(['-h', f'int:value:{int(progress)}'])
        if self.root.current_notify_id:
            cmd.extend(['--replace-id', self.root.current_notify_id.strip()])
            
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        self.root.current_notify_id, _ = process.communicate()

    def _on_clone_progress(self, message, progress):
        if self.window is None:
            return

        if message:
            self._send_notification(
                "Clonando Repositorio",
                message,
                icon="dialog-information",
                progress=progress
            )

    def _on_clone_finished(self, success, message):
        if self.window is None:
            return
    
        self._set_busy(False)
        self._update_clone_button_state()

        if success:
            self._send_notification(
                "Clonado completado",
                "El repositorio se clonó correctamente.",
                icon="dialog-ok",
                progress=100,
                force=True
            )
            self.root.home.switch_to_ide(message.strip('"'))
        else:
            self._send_notification(
                "Error al clonar",
                message or "Ocurrió un error durante el proceso de clonación.",
                icon="dialog-no",
                progress=0,
                force=True
            )