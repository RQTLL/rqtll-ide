import subprocess
import time
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt, QTimer, QObject, QModelIndex
from external.rqt2_widgets.forms.f4_ui_package_manager import Ui_Widget as Ui_F4
from external.rqt2_widgets.utils.base_window import DemoWindow

from .common import PackageSearchThread, PackageLoader, PackageInstaller

class PackageManagerController(QObject):
    def __init__(self, root_controller, parent_window):
        super().__init__()
        self.root = root_controller
        self.parent_win = parent_window
        self.is_busy = False
        self.last_install_success = False
        self.last_notify_time = 0.0
        
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._do_search)

    def open(self, trigger_button=None):
        self.trigger_button = trigger_button
        if self.trigger_button: 
            self.trigger_button.setEnabled(False)

        self.f4 = DemoWindow(Ui_F4, title="RQT2 IDE / Gestor de Dependencias", 
                             icon_dirs=self.root.icon_dirs, parent=self.parent_win, 
                             theme=self.root.theme)
        self.f4.setAttribute(Qt.WA_DeleteOnClose)
        
        self.safe_disconnect(self.f4.ui.BTNCancell)
        self.safe_disconnect(self.f4.ui.BTNApply)
        self.safe_disconnect(self.f4.ui.BTNAccept)
        self.f4.ui.BTNCancell.clicked.connect(self.f4.close)
        self.f4.ui.EDITSearch.textChanged.connect(self.on_search_changed)
        self.f4.ui.BTNAccept.clicked.connect(self._on_accept_packages)
        self.f4.ui.BTNApply.clicked.connect(self._on_apply_packages)
        
        self.f4.destroyed.connect(self._on_window_destroyed)
        self.f4.closeEvent = self._handle_close_event

        self.f4.ui.EDITSearch.setEnabled(False)
        self.f4.ui.EDITSearch.setPlaceholderText("Cargando lista de ROS 2...")

        self.loader = PackageLoader(filter_text="", stub=self.root.package_stub)
        self.loader.package_received.connect(self.add_pkg_to_ui)
        
        self.loader.finished.connect(self._on_initial_load_finished)
        self.loader.start()
        self.f4.show()

    def safe_disconnect(self, item):
        try:
            item.clicked.disconnect()
        except Exception:
            pass

    def _on_initial_load_finished(self):
        try:
            if self.f4 and self.f4.ui.EDITSearch:
                self.f4.ui.EDITSearch.setEnabled(True)
                self.f4.ui.EDITSearch.setPlaceholderText("Buscar paquetes...")
        except RuntimeError: pass

    def _send_dynamic_notification(self, title, msg, icon=None, progress=None, force=False):
        now = time.time()
        if not force and progress is not None:
            if now - self.last_notify_time < 0.5:
                return
        self.last_notify_time = now

        cmd = ['notify-send', '--app-name', 'RQT2 IDE', '--print-id', title, msg]
        if icon: cmd.extend(['--icon', icon])
        if progress is not None:
            cmd.extend(['-h', f'int:value:{int(progress)}'])
        if self.root.current_notify_id:
            cmd.extend(['--replace-id', self.root.current_notify_id.strip()])
        
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        self.root.current_notify_id, _ = process.communicate()

    def on_search_changed(self, text):
        if hasattr(self, 'search_thread') and self.search_thread.isRunning():
            self.search_thread.cancel()
            self.search_thread.wait()
        
        self.search_timer.stop()
        self.search_timer.start(300)
        
        self.f4.ui.pkg_model.beginResetModel()
        self.f4.ui.pkg_model._data = [] 
        self.f4.ui.pkg_model.endResetModel()

    def _do_search(self):
        try:
            if not hasattr(self, 'f4') or self.f4 is None:
                return
            
            query = self.f4.ui.EDITSearch.text() 
            
            self.search_thread = PackageSearchThread(query, self.root.package_stub)
            self.search_thread.packages_received.connect(self.update_package_table)
            self.search_thread.start()
        except (RuntimeError, AttributeError):
            self.search_timer.stop()

    def update_package_table(self, packages):
        self.f4.ui.pkg_model.beginResetModel()
        self.f4.ui.pkg_model._data = packages
        self.f4.ui.pkg_model.endResetModel()

    def _on_apply_packages(self):
        target_pkg = next((p for p in self.f4.ui.pkg_model._data if p.get('pending')), None)
    
        if not target_pkg:
            return

        self._execute_package_action(close_after=False)

    def _on_accept_packages(self):
        target_pkg = next((p for p in self.f4.ui.pkg_model._data if p.get('pending')), None)
        if not target_pkg:
            self.f4.close()
            return
        self._execute_package_action(close_after=True)

    def _execute_package_action(self, close_after=False):
        if self.is_busy: return
        
        self.pending_queue = [pkg for pkg in self.f4.ui.pkg_model._data if pkg.get('pending')]
        
        if not self.pending_queue:
            if close_after: self.f4.close()
            return

        self._set_ui_busy(True)
        self._process_next_in_queue(close_after)

    def _process_next_in_queue(self, close_after):
        if not self.pending_queue:
            self._set_ui_busy(False)
            self.root.current_notify_id = None
            if close_after: self.f4.close()
            return

        target_pkg = self.pending_queue.pop(0)
        pkg_name = target_pkg['name']
        is_un = target_pkg.get('installed', False)
        
        if is_un:
            if not self._confirm_action(pkg_name):
                self._process_next_in_queue(close_after)
                return

        # Initialize tracking for the current package operation
        self.current_action_packages = []
        self.completed_packages = set()
        self.current_action_type = "remove" if is_un else "install"
        self.capture_packages = False
        self.last_install_success = False
        
        icon = "edit-delete" if is_un else "system-software-install"
        self._send_dynamic_notification("RQT2 Gestor", f"Procesando {pkg_name}...", icon=icon, force=True)

        self.installer_thread = PackageInstaller(pkg_name, self.root.package_stub)
        self.installer_thread.log_received.connect(self._update_logs)
        self.installer_thread.finished_ok.connect(
            lambda n: self._finish_step(n, is_un, close_after)
        )
        self.installer_thread.start()

    def _finish_step(self, name, was_un, close_after):
        if self.last_install_success:
            model = self.f4.ui.pkg_model
            for i, pkg in enumerate(model._data):
                if pkg['name'] == name:
                    pkg['installed'] = not was_un
                    pkg['pending'] = False
                    
                    left = model.index(i, 0)
                    right = model.index(i, 2)
                    model.dataChanged.emit(left, right, [Qt.ItemDataRole.DisplayRole])
                    break

        if hasattr(self.f4.ui, '_update_apply_button'):
            self.f4.ui._update_apply_button()

        status_icon = 'dialog-ok' if self.last_install_success else 'dialog-ok'
        self._send_dynamic_notification(
            "Operación Exitosa" if self.last_install_success else "Operación Fallida",
            f"Cambios terminados en {name}.", 
            icon=status_icon,
            force=True
        )

        self._process_next_in_queue(close_after)

    def _update_logs(self, msg, prog):
        if "SUCCESS_COMPLETE" in msg: 
            self.last_install_success = True
        elif "ERROR_CANCELLED" in msg: 
            self.last_install_success = False
        elif "ERROR_LAUNCH_FAILED" in msg:
            self.last_install_success = False
        else:
            self._parse_log_line(msg)

    def _parse_log_line(self, line):
        line_strip = line.strip()
        if not line_strip:
            return

        # Headers that indicate list of packages
        if ("paquetes se ELIMINARÁN" in line or 
            "paquetes adicionales" in line or 
            "paquetes NUEVOS" in line):
            self.capture_packages = True
            return

        # End of package list indicators
        if self.capture_packages:
            if "actualizados" in line or "actualizados," in line or "necesita descargar" in line or "utilizarán" in line:
                self.capture_packages = False
            else:
                for word in line_strip.split():
                    word_clean = word.strip(":,()[]{}")
                    if word_clean and not word_clean.startswith("-") and not word_clean.startswith("/"):
                        if word_clean not in self.current_action_packages:
                            self.current_action_packages.append(word_clean)

        for pkg in self.current_action_packages:
            if pkg in line_strip:
                if ("Desempaquetando" in line_strip or 
                    "Configurando" in line_strip or 
                    "Desinstalando" in line_strip or 
                    "Eliminando" in line_strip):
                    if self.current_action_type == "install" and "Configurando" in line_strip:
                        self.completed_packages.add(pkg)
                    elif self.current_action_type == "remove" and ("Eliminando" in line_strip or "Desinstalando" in line_strip):
                        self.completed_packages.add(pkg)

                    self._update_progress_notification(pkg, line_strip)

    def _update_progress_notification(self, pkg_name, action_line):
        total = len(self.current_action_packages)
        completed = len(self.completed_packages)
        
        action_text = "Procesando"
        if "Desempaquetando" in action_line:
            action_text = f"Desempaquetando {pkg_name}"
        elif "Configurando" in action_line:
            action_text = f"Configurando {pkg_name}"
        elif "Desinstalando" in action_line or "Eliminando" in action_line:
            action_text = f"Eliminando {pkg_name}"
        elif "Seleccionando" in action_line:
            action_text = f"Seleccionando {pkg_name}"

        if total > 0:
            progress = int((completed / total) * 100)
            msg = f"{action_text}\n({completed} de {total} paquetes completados)"
        else:
            progress = 10
            msg = f"{action_text}..."

        title = "Instalando Paquetes" if self.current_action_type == "install" else "Eliminando Paquetes"
        icon = "system-software-install" if self.current_action_type == "install" else "edit-delete"
        
        self._send_dynamic_notification(title, msg, icon=icon, progress=progress)

    def _finish_action(self, name, was_un, close_after):
        self._set_ui_busy(False)
        
        if self.last_install_success:
            model = self.f4.ui.pkg_model
            for i, pkg in enumerate(model._data):
                if pkg['name'] == name:
                    pkg['installed'] = not was_un
                    pkg['pending'] = False
                    
                    left = model.index(i, 0)
                    right = model.index(i, 2)
                    model.dataChanged.emit(left, right, [Qt.ItemDataRole.DisplayRole])
                    break
            
        if hasattr(self.f4.ui, '_update_apply_button'):
            self.f4.ui._update_apply_button()

        status_icon = 'dialog-ok' if self.last_install_success else 'dialog-no'
        title = "Operación Exitosa" if self.last_install_success else "Operación Fallida"
        msg = f"Cambios terminados en {name}." if self.last_install_success else "Proceso cancelado."
        self._send_dynamic_notification(title, msg, icon=status_icon)

        if close_after and self.last_install_success:
            self.f4.close()

    def _set_ui_busy(self, busy):
        self.is_busy = busy
        self.f4.ui.BTNAccept.setEnabled(not busy)
        self.f4.ui.BTNApply.setEnabled(not busy)
        self.f4.ui.BTNCancell.setEnabled(not busy)
        self.f4.ui.EDITSearch.setEnabled(not busy)

    def _confirm_action(self, name):
        """Diálogo de confirmación con estilo RQT2."""
        msg_box = QMessageBox(self.f4)
        msg_box.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle("RQT2 | Confirmación")
        msg_box.setText(f"¿Confirmas la eliminación de {name}?")
        msg_box.setInformativeText("Esta acción es irreversible y puede afectar dependencias de ROS 2.")
        
        yes_button = msg_box.addButton("Confirmar", QMessageBox.ButtonRole.AcceptRole)
        no_button = msg_box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(no_button)

        msg_box.exec()
        return msg_box.clickedButton() == yes_button

    def _handle_close_event(self, event):
        if self.is_busy: event.ignore()
        else: event.accept()

    def _on_window_destroyed(self):
        self.search_timer.stop()
    
        if hasattr(self, 'search_thread') and self.search_thread.isRunning():
            self.search_thread.cancel()
            self.search_thread.wait()

        if hasattr(self, 'loader') and self.loader.isRunning():
            self.loader.cancel()
            self.loader.wait()

        if self.trigger_button:
            try:
                self.trigger_button.setEnabled(True)
            except RuntimeError: 
                pass
            
        self.f4 = None

    def add_pkg_to_ui(self, pkg):
        model = self.f4.ui.pkg_model
        row = model.rowCount()
        model.beginInsertRows(QModelIndex(), row, row)
        model._data.append({'name': pkg.name, 'installed': pkg.is_installed, 'pending': False})
        model.endInsertRows()
