import sys, os, webbrowser, subprocess

import grpc
import packages_pb2
import packages_pb2_grpc

from PySide6.QtWidgets import QApplication, QFileDialog, QSystemTrayIcon, QMenu, QMessageBox
from PySide6.QtGui import QFontDatabase, QFont, QIcon
from PySide6.QtCore import Qt, QThread, Signal, QModelIndex, QTimer

from external.rqt2_widgets.forms.f0_ui_main import Ui_Widget as Ui_F0
from external.rqt2_widgets.forms.f1_ui_new_ws import Ui_Widget as Ui_F1
from external.rqt2_widgets.forms.f3_ui_clone_ws import Ui_Widget as Ui_F3
from external.rqt2_widgets.forms.f4_ui_package_manager import Ui_Widget as Ui_F4
from external.rqt2_widgets.forms.ui_form import Ui_Widget as Ui_Form

from external.rqt2_widgets.utils.base_window import DemoWindow

base_path = os.path.dirname(os.path.abspath(__file__))
icon_dirs = [
    os.path.join(base_path, "external", "rqt2_components"),
    os.path.join(base_path, "external", "rqt2_components", "assets"),
    os.path.join(base_path, "external", "rqt2_components", "assets", "branding"),
    os.path.join(base_path, "external", "rqt2_components", "assets", "icons"),
    os.path.join(base_path, "external", "rqt2_components", "styles"),
    os.path.join(base_path, "external", "rqt2_components", "styles", "themes"),
    os.path.join(base_path, "external", "rqt2_widgets"),
]

def load_resources(app, components_path):
    fonts_path = os.path.join(components_path, "assets/fonts")
    for root, dirs, files in os.walk(fonts_path):
        for file in files:
            if file.endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(root, file))

    qss_file = os.path.join(components_path, "styles/themes/dark.qss")
    if os.path.exists(qss_file):
        with open(qss_file, "r") as f:
            app.setStyleSheet(f.read())

class PackageSearchThread(QThread):
    packages_received = Signal(list)

    def __init__(self, query, stub):
        super().__init__()
        self.query = query
        self.stub = stub

    def run(self):
        try:
            packages = []
            request = packages_pb2.ListPackagesRequest(filter=self.query)
            for pkg in self.stub.ListAvailablePackages(request):
                packages.append({
                    'name': pkg.name,
                    'installed': pkg.is_installed,
                    'pending': False
                })
            self.packages_received.emit(packages)
        except Exception:
            pass

class PackageLoader(QThread):
    package_received = Signal(object)

    def __init__(self, filter_text="", stub=None):
        super().__init__()
        self.filter_text = filter_text
        self.stub = stub

    def run(self):
        try:
            request = packages_pb2.ListPackagesRequest(filter=self.filter_text)
            for pkg in self.stub.ListAvailablePackages(request):
                self.package_received.emit(pkg)
        except Exception as e:
            pass
            #print(f"gRPC err: {e}")

class PackageInstaller(QThread):
    log_received = Signal(str, float)
    finished_ok = Signal(str)

    def __init__(self, package_name, stub):
        super().__init__()
        self.package_name = package_name
        self.stub = stub

    def run(self):
        try:
            request = packages_pb2.InstallRequest(package_name=self.package_name)
            for response in self.stub.InstallPackage(request):
                self.log_received.emit(response.log_line, response.progress)
        except Exception as e:
            self.log_received.emit(f"i err: {e}", 0)
        self.finished_ok.emit(self.package_name)

class RQT2Controller:
    def __init__(self, icon_dirs=icon_dirs, theme="dark.qss"):
        self.theme = theme
        self.active_dialogs = []
        self.is_busy = False

        self.channel = grpc.insecure_channel('127.0.0.1:50051')
        self.package_stub = packages_pb2_grpc.PackageServiceStub(self.channel)
        
        self.f0 = DemoWindow(Ui_F0, title="RQT2 IDE", icon_dirs=icon_dirs, theme=self.theme)

        self.tray_icon = QSystemTrayIcon(self.f0)
        logo_path = os.path.join(base_path, "external/rqt2_components/assets/branding/logo.svg")
        self.tray_icon.setIcon(QIcon(logo_path))
        tray_menu = QMenu()
        quit_action = tray_menu.addAction("Salir de RQT2")
        quit_action.triggered.connect(QApplication.instance().quit)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()

        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._do_search)

        self.show_startup_notification()
        self.setup_f0_connections()
        self.f0.show()

    def show_startup_notification(self):
        try:
            request = packages_pb2.ListPackagesRequest(filter="ros-base")
            response_iter = self.package_stub.ListAvailablePackages(request)
            first_pkg = next(response_iter)
            distro = first_pkg.version if first_pkg.version else "Jazzy"
            logo_path = os.path.join(base_path, "external/rqt2_components/assets/branding/logo.svg")

            self.notify_id, _ = subprocess.Popen([
                'notify-send',
                '--app-name', 'RQT2 IDE',
                '--print-id',
                '--icon', logo_path,
                'RQT2 IDE',
                f"Motor funcionando. ROS 2 {distro} listo."
            ], stdout=subprocess.PIPE, text=True).communicate()
        
            self.tray_icon.show()

        except Exception as e:
            self.notify_id, _ = subprocess.Popen([
                'notify-send', 
                '--app-name', 'RQT2 IDE',
                '--print-id',
                '--icon', logo_path,
                'RQT2 Error', 
                'Backend offline'
            ], stdout=subprocess.PIPE, text=True).communicate()

    def setup_f0_connections(self):
        self.f0.ui.FRAMENew.clicked.connect(self.open_f1)
        self.f0.ui.FRAMEOpen.clicked.connect(self.open_file_dialog)
        self.f0.ui.FRAMEClone.clicked.connect(self.open_f3)
        self.f0.ui.NAVInstall.clicked.connect(lambda: self.open_f4(self.f0.ui.NAVInstall))
        self.f0.ui.NAVDocs.clicked.connect(self.open_docs)

    def open_f1(self):
        self.f1 = DemoWindow(
            Ui_F1, 
            title="Nuevo espacio", 
            icon_dirs=icon_dirs, 
            parent=self.f0, 
            theme=self.theme
        )
        self.f1.setAttribute(Qt.WA_DeleteOnClose)
        self.f0.ui.FRAMENew.setEnabled(False)

        def safe_enable():
            try:
                if self.f0.ui.FRAMENew:
                    if not self.f0.ui.FRAMENew.isHidden():
                        self.f0.ui.FRAMENew.setEnabled(True)
            except RuntimeError:
                pass
        self.f1.ui.BTNCancell.clicked.connect(self.f1.close)
        self.f1.destroyed.connect(safe_enable)

        self.f1.ui.BTNMake.clicked.connect(lambda: self.switch_to_ide("Nuevo"))

        self.f1.show()
        self.active_dialogs.append(self.f1)

    def open_file_dialog(self):
        path = QFileDialog.getExistingDirectory(self.f0, "Cargar Espacio de Trabajo")
        if path:
            self.switch_to_ide(path)

    def open_f3(self):
        self.f3 = DemoWindow(
            Ui_F3, 
            title="Clonar espacio", 
            icon_dirs=icon_dirs, 
            parent=self.f0, 
            theme=self.theme
        )
        self.f3.setAttribute(Qt.WA_DeleteOnClose)
        self.f0.ui.FRAMEClone.setEnabled(False)
        
        def safe_enable():
            try:
                if self.f0.ui.FRAMEClone:
                    if not self.f0.ui.FRAMEClone.isHidden():
                        self.f0.ui.FRAMEClone.setEnabled(True)
            except RuntimeError:
                pass
        self.f3.ui.BTNCancell.clicked.connect(self.f3.close)
        self.f3.destroyed.connect(safe_enable)

        self.f3.ui.BTNClone.clicked.connect(lambda: self.switch_to_ide("Nuevo"))
        
        self.f3.show()
        self.active_dialogs.append(self.f3)

    def open_f4(self, trigger_button=None):
        current_parent = self.main_ide if hasattr(self, 'main_ide') and self.main_ide.isVisible() else self.f0
    
        if trigger_button:
            trigger_button.setEnabled(False)

        self.f4 = DemoWindow(
            Ui_F4, 
            title="RQT2 IDE / Gestor de Dependencias", 
            icon_dirs=icon_dirs, 
            parent=current_parent, 
            theme=self.theme
        )
        self.f4.setAttribute(Qt.WA_DeleteOnClose)

        def safe_enable():
            try:
                if trigger_button:
                    trigger_button.setEnabled(True)
            except RuntimeError:
                pass
        
        def safe_disconnect(item):
            try:
                item.clicked.disconnect()
            except Exception:
                pass

        def lock_close_event(event):
            if hasattr(self, 'installer_thread') and self.installer_thread.isRunning():
                subprocess.Popen([
                    'notify-send', 
                    '--app-name', 'RQT2 IDE',
                    '--replace-id', self.notify_id.strip(),
                    '--icon', logo_path,
                    'Acción bloqueada', 
                    'No puedes cerrar la ventana durante la instalación.'
                ])
                event.ignore()
            else:
                event.accept()

        safe_disconnect(self.f4.ui.BTNCancell)
        safe_disconnect(self.f4.ui.BTNApply)
        safe_disconnect(self.f4.ui.BTNAccept)

        self.f4.ui.BTNCancell.clicked.connect(self.f4.close)
        self.f4.destroyed.connect(safe_enable)

        self.f4.ui.EDITSearch.textChanged.connect(self.on_search_changed)
        
        self.f4.ui.BTNAccept.clicked.connect(self._on_accept_packages)
        self.f4.ui.BTNApply.clicked.connect(self._on_apply_packages)

        self.thread = PackageLoader(filter_text="", stub=self.package_stub)
        self.thread.package_received.connect(self.add_pkg_to_ui)
        self.thread.start()
    
        self.f4.closeEvent = lock_close_event
        self.f4.show()
        self.active_dialogs.append(self.f4)

    def open_docs(self):
        webbrowser.open('https://www.google.com')

    def switch_to_ide(self, ws_path):
        for dialog in self.active_dialogs:
            if dialog:
                if not dialog.isHidden():
                    dialog.close()
        
        self.f0.close()
        self.main_ide = DemoWindow(
            Ui_Form, 
            title=f"RQT2 IDE / {ws_path.split('/')[-1]}", 
            icon_dirs=icon_dirs, 
            show_daemon=True, show_tab=True, 
            theme=self.theme
        )
        self.main_ide.show()
        self.main_ide.raise_()
        self.main_ide.activateWindow()

    def _on_accept_packages(self):
        target_pkg = next((pkg for pkg in self.f4.ui.pkg_model._data if pkg.get('pending')), None)
    
        if not target_pkg:
            self.f4.close()
            return

        self._execute_package_action(close_after=True)

    def _execute_package_action(self, close_after=False):
        if self.is_busy:
            return

        target_pkg = next((pkg for pkg in self.f4.ui.pkg_model._data if pkg.get('pending')), None)
        pkg_name = target_pkg['name']
        is_uninstalling = target_pkg.get('installed', False)

        if is_uninstalling:
            msg_box = QMessageBox(self.f4)
        
            msg_box.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("RQT2 | Confirmación")
            msg_box.setText(f"¿Confirmas la eliminación de {pkg_name}?")
            msg_box.setInformativeText("Esta acción es irreversible y puede afectar dependencias de ROS 2.")
        
            yes_button = msg_box.addButton("Confirmar", QMessageBox.ButtonRole.AcceptRole)
            no_button = msg_box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(no_button)

            msg_box.exec()
        
            if msg_box.clickedButton() == no_button:
                return

        self.is_busy = True
        self.f4.ui.EDITSearch.setEnabled(False)
        self.f4.ui.BTNAccept.setEnabled(False)
        self.f4.ui.BTNApply.setEnabled(False)
        self.f4.ui.BTNCancell.setEnabled(False)
        self.f0.ui.NAVInstall.setEnabled(False)
        
        self.notify_pk, _ = subprocess.Popen([
            'notify-send',
            '--app-name', 'RQT2 IDE',
            '--print-id',
            '--icon', action_icon,
            f'Gestor de Paquetes: ',
            f"{action_title} {pkg_name}..."
        ], stdout=subprocess.PIPE, text=True).communicate()

        self.installer_thread = PackageInstaller(pkg_name, self.package_stub)
        self.installer_thread.log_received.connect(self.update_install_log)
    
        self.installer_thread.finished_ok.connect(self._unlock_ui)
        if close_after:
            self.installer_thread.finished_ok.connect(lambda name: self.on_install_finished(name, is_uninstalling))
            self.installer_thread.finished_ok.connect(self.f4.close)
        else:
            self.installer_thread.finished_ok.connect(lambda name: self.on_install_finished(name, is_uninstalling))
    
        self.installer_thread.start()

    def add_pkg_to_ui(self, pkg):
        try:
            new_package = {
                'name': pkg.name,
                'installed': pkg.is_installed,
                'pending': False
            }

            model = self.f4.ui.pkg_model
            row_position = model.rowCount()
        
            model.beginInsertRows(QModelIndex(), row_position, row_position)
            model._data.append(new_package)
            model.endInsertRows()
        
        except Exception as e:
            return

    def on_search_changed(self, text):
        if hasattr(self, 'search_thread') and self.search_thread.isRunning():
            self.search_thread.terminate()
            self.search_thread.wait()

        self.search_timer.stop()
        self.search_timer.start(300)
    
        self.f4.ui.pkg_model.beginResetModel()
        self.f4.ui.pkg_model._data = [] 
        self.f4.ui.pkg_model.endResetModel()

    def _do_search(self):
        query = self.f4.ui.EDITSearch.text()
        
        self.search_thread = PackageSearchThread(query, self.package_stub)
        self.search_thread.packages_received.connect(self.update_package_table)
        self.search_thread.start()

    def update_package_table(self, packages):
        self.f4.ui.pkg_model.beginResetModel()
        self.f4.ui.pkg_model._data = packages
        self.f4.ui.pkg_model.endResetModel()

    def _on_apply_packages(self):
        if self.is_busy:
            return
        
        target_pkg = next((pkg for pkg in self.f4.ui.pkg_model._data if pkg.get('pending')), None)
    
        if not target_pkg:
            return

        pkg_name = target_pkg['name']
        is_uninstalling = target_pkg.get('installed', True) 
    
        action_title = "Desinstalando" if is_uninstalling else "Instalando"
        action_icon = "edit-delete" if is_uninstalling else "system-software-install"

        if is_uninstalling:
            msg_box = QMessageBox(self.f4)
        
            msg_box.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle("RQT2 | Confirmación")
            msg_box.setText(f"¿Confirmas la eliminación de {pkg_name}?")
            msg_box.setInformativeText("Esta acción es irreversible y puede afectar dependencias de ROS 2.")
        
            yes_button = msg_box.addButton("Confirmar", QMessageBox.ButtonRole.AcceptRole)
            no_button = msg_box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
            msg_box.setDefaultButton(no_button)

            msg_box.exec()
        
            if msg_box.clickedButton() == no_button:
                return

        self.is_busy = True
        self.f4.ui.EDITSearch.setEnabled(False)
        self.f4.ui.BTNAccept.setEnabled(False)
        self.f4.ui.BTNApply.setEnabled(False)
        self.f4.ui.BTNCancell.setEnabled(False)
        self.f0.ui.NAVInstall.setEnabled(False)

        self.notify_pk, _ = subprocess.Popen([
            'notify-send',
            '--app-name', 'RQT2 IDE',
            '--print-id',
            '--icon', action_icon,
            f'Gestor de Paquetes: ',
            f"{action_title} {pkg_name}..."
        ], stdout=subprocess.PIPE, text=True).communicate()


        self.installer_thread = PackageInstaller(pkg_name, self.package_stub)
        self.installer_thread.log_received.connect(self.update_install_log)
        self.installer_thread.finished_ok.connect(self._unlock_ui)
        self.installer_thread.finished_ok.connect(lambda name: self.on_install_finished(name, is_uninstalling))
        self.installer_thread.start()


    def update_install_log(self, message, progress):
        #print(f"APT: {message}") 
        if progress > 0:
            pass
        if "SUCCESS_COMPLETE" in message:
            self.last_install_success = True
        elif "ERROR_CANCELLED" in message:
            self.last_install_success = False

    def on_install_finished(self, name, was_uninstalling):
        self.f4.ui.BTNApply.setEnabled(True)
    
        title = "Desinstalación Completada" if was_uninstalling else "Instalación Completada"
        msg = f"{name} eliminado correctamente." if was_uninstalling else f"{name} instalado con éxito."
    
        if not self.last_install_success:
            subprocess.Popen([
                'notify-send', 
                '--app-name', 'RQT2 IDE',
                '--replace-id', self.notify_pk.strip(),
                'Operación Cancelada', 
                f"No se realizaron cambios en {name}."
            ])
        else:
            subprocess.Popen([
                'notify-send',
                '--app-name', 'RQT2 IDE',
                '--replace-id', self.notify_pk.strip(),
                '--icon', 'emblem-success',
                title,
                msg
            ])
    
        self.on_search_changed(self.f4.ui.EDITSearch.text())

    def _unlock_ui(self):
        self.is_busy = False
        self.f0.ui.NAVInstall.setEnabled(True)
    
        if hasattr(self, 'f4') and self.f4.isVisible():
            self.f4.ui.EDITSearch.setEnabled(True)
            self.f4.ui.BTNAccept.setEnabled(True)
            self.f4.ui.BTNApply.setEnabled(True)
            self.f4.ui.BTNCancell.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    base_path = os.path.dirname(os.path.abspath(__file__))
    comp_path = os.path.join(base_path, "external/rqt2_components")
    
    load_resources(app, comp_path)
    
    controller = RQT2Controller(icon_dirs=icon_dirs)
    sys.exit(app.exec())
