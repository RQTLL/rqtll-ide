import os
from PySide6.QtCore import Qt, QObject, QTimer, QModelIndex
from PySide6.QtWidgets import QApplication, QMessageBox
from external.rqt2_widgets.utils.base_window import DemoWindow

import grpc
import installer_pb2
from ..common import PackageSearchThread, PackageLoader, PackageInstaller
from .workers import PackageListWorker, RepoSetupWorker, EnvInstallWorker, ConfigureEnvWorker

from external.rqt2_widgets.forms.f5_ui_wizard_init import Ui_Widget as Ui_WizInit
from external.rqt2_widgets.forms.f6_ui_wizard_opt import Ui_Widget as Ui_WizOpt
from external.rqt2_widgets.forms.f7_ui_wizard_install_config import Ui_Widget as Ui_WizConfig
from external.rqt2_widgets.forms.f8_ui_wizard_installed import Ui_Widget as Ui_WizProgress
from external.rqt2_widgets.forms.f9_ui_wizard_close import Ui_Widget as Ui_WizClose

class WizardController(QObject):
    def __init__(self, root_controller):
        super().__init__()
        self.root = root_controller
        self.current_window = None
        self.steps = [
            (Ui_WizInit, "RQT2 IDE / Asistente de Instalación"),
            (Ui_WizOpt, "RQT2 IDE / Opciones de Instalación"),
            (Ui_WizConfig, "RQT2 IDE / Versión de ROS2"),
            (Ui_WizProgress, "RQT2 IDE / Progreso de Instalación"),
            (Ui_WizClose, "RQT2 IDE / Finalizar Instalación")
        ]
        self.current_step_idx = 0
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(self._do_package_search)
        self.pending_packages = {}
        
    def start(self):
        self.current_step_idx = 0
        self._show_step(self.current_step_idx)
        
    def _show_step(self, idx):
        if idx < 0 or idx >= len(self.steps):
            return
            
        ui_class, title = self.steps[idx]
        
        # Save previous window position if exists
        pos = None
        if self.current_window:
            if self.current_step_idx == 2:
                self._cleanup_step2()
            pos = self.current_window.pos()
            self.current_window.close()
            
        self.current_window = DemoWindow(ui_class, title=title,
                                         icon_dirs=self.root.icon_dirs,
                                         theme=self.root.theme)
        
        if pos:
            self.current_window.move(pos)
            
        self._connect_buttons(idx)
        if idx == 0:
            if hasattr(self.current_window.ui, "BTNBack"):
                self.current_window.ui.BTNBack.setEnabled(False)
            self._load_colored_logo()
        elif idx == 2:
            self._init_config_step()
        elif idx == 3:
            self._init_progress_step()
            
        self.current_window.show()
        
    def _connect_buttons(self, idx):
        ui = self.current_window.ui
        
        # Connect Cancel buttons
        if hasattr(ui, "BTNCancell"):
            ui.BTNCancell.clicked.connect(self.cancel_wizard)
        if hasattr(ui, "BTNCancel"):
            ui.BTNCancel.clicked.connect(self.cancel_wizard)
            
        # Connect Back buttons
        if hasattr(ui, "BTNBack"):
            ui.BTNBack.clicked.connect(self.go_back)
            
        # Connect Next buttons
        if hasattr(ui, "BTNNext"):
            ui.BTNNext.clicked.connect(self.go_next)
            
        # Connect Finish/Close button in the last step
        if hasattr(ui, "BTNFinish"):
            ui.BTNFinish.clicked.connect(self.finish_wizard)
            
    def go_back(self):
        if self.current_step_idx > 0:
            self.current_step_idx -= 1
            self._show_step(self.current_step_idx)
            
    def go_next(self):
        if self.current_step_idx == 1:
            ui = self.current_window.ui
            if hasattr(ui, "CBInstallRos"):
                if not ui.CBInstallRos.isChecked():
                    if self.current_window:
                        self.current_window.close()
                    self.root.open_home()
                    return
                else:
                    msg_box = QMessageBox(self.current_window)
                    msg_box.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
                    msg_box.setIcon(QMessageBox.Icon.Warning)
                    msg_box.setWindowTitle("RQT2 | Confirmación")
                    msg_box.setText("Se agregarán los repositorios de ROS2")
                    msg_box.setInformativeText("Esta acción requiere permisos de administrador para configurar las fuentes de apt.")
                    
                    yes_button = msg_box.addButton("Confirmar", QMessageBox.ButtonRole.AcceptRole)
                    no_button = msg_box.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
                    msg_box.setDefaultButton(no_button)
                    
                    msg_box.exec()
                    if msg_box.clickedButton() != yes_button:
                        return
                        
                    # Disable buttons while installing
                    ui.BTNNext.setEnabled(False)
                    ui.BTNBack.setEnabled(False)
                    ui.BTNCancel.setEnabled(False)
                    
                    # Call SetupRepositories
                    self.worker = RepoSetupWorker(self.root)
                    self.worker.finished.connect(self._on_repo_setup_finished)
                    self.worker.start()
                    return
        elif self.current_step_idx == 3:
            ui = self.current_window.ui
            load_ros_shell = ui.CBLoadRosShell.isChecked()
            config_domain_id = ui.CBConfigDomainId.isChecked()
            domain_id = ui.spinBox.value()

            if load_ros_shell or config_domain_id:
                if config_domain_id and domain_id == 0:
                    msg_box = QMessageBox(self.current_window)
                    msg_box.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
                    msg_box.setIcon(QMessageBox.Icon.Warning)
                    msg_box.setWindowTitle("RQT2 | Advertencia")
                    msg_box.setText("El ROS_DOMAIN_ID configurado es 0.")
                    msg_box.setInformativeText("Un dominio 0 es el valor predeterminado y puede causar interferencias si hay otros dispositivos ROS 2 en la misma red.\n\n¿Desea continuar?")
                    
                    yes_button = msg_box.addButton("Sí, continuar", QMessageBox.ButtonRole.AcceptRole)
                    no_button = msg_box.addButton("No, corregir", QMessageBox.ButtonRole.RejectRole)
                    msg_box.setDefaultButton(no_button)
                    
                    msg_box.exec()
                    if msg_box.clickedButton() != yes_button:
                        return

                ui.BTNNext.setEnabled(False)
                ui.BTNBack.setEnabled(False)
                ui.BTNCancel.setEnabled(False)

                import re
                distro = "humble"
                if hasattr(self, 'selected_ros_package') and self.selected_ros_package:
                    match = re.search(r"ros-([a-z]+)-(ros-core|desktop|desktop-full)", self.selected_ros_package)
                    if match:
                        distro = match.group(1)

                self.config_worker = ConfigureEnvWorker(
                    self.root.installer_stub,
                    load_ros_shell,
                    config_domain_id,
                    domain_id,
                    distro
                )
                self.config_worker.progress_updated.connect(self._on_config_progress)
                self.config_worker.finished.connect(self._on_config_finished)
                self.config_worker.start()
                return

        if self.current_step_idx < len(self.steps) - 1:
            self.current_step_idx += 1
            self._show_step(self.current_step_idx)

    def _on_repo_setup_finished(self, success, error_msg):
        if hasattr(self.current_window, "ui"):
            ui = self.current_window.ui
            ui.BTNNext.setEnabled(True)
            ui.BTNBack.setEnabled(True)
            ui.BTNCancel.setEnabled(True)
            
        if success:
            if self.current_step_idx < len(self.steps) - 1:
                self.current_step_idx += 1
                self._show_step(self.current_step_idx)
        else:
            error_box = QMessageBox(self.current_window)
            error_box.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
            error_box.setIcon(QMessageBox.Icon.Critical)
            error_box.setWindowTitle("RQT2 | Error")
            error_box.setText("No se pudieron configurar los repositorios")
            error_box.setInformativeText(error_msg)
            error_box.addButton("Aceptar", QMessageBox.ButtonRole.AcceptRole)
            error_box.exec()
            
    def cancel_wizard(self):
        if self.current_window:
            self.current_window.close()
        QApplication.quit()
        
    def finish_wizard(self):
        if self.current_window:
            self.current_window.close()
        self.root.open_home()

    def _init_config_step(self):
        ui = self.current_window.ui
        self._clear_layout(ui.gridLayout_options)
        ui.BTNNext.setEnabled(False)
        
        self.package_worker = PackageListWorker(self.root.package_stub)
        self.package_worker.packages_received.connect(self._on_packages_loaded)
        self.package_worker.start()

        ui.EDITSearch.setEnabled(False)
        ui.EDITSearch.setPlaceholderText("Cargando lista de ROS 2...")
        try:
            ui.EDITSearch.textChanged.connect(self.on_search_changed)
            ui.CBOPT1Search.stateChanged.connect(lambda: self.on_search_changed(""))
            ui.CBOPT2Search.stateChanged.connect(lambda: self.on_search_changed(""))
            ui.CBRti.stateChanged.connect(lambda: self.on_search_changed(""))
            ui.pkg_view.clicked.connect(self._on_table_clicked)
        except Exception:
            pass

        ui.pkg_model.beginResetModel()
        ui.pkg_model._data = []
        ui.pkg_model.endResetModel()

        self.pkg_loader = PackageLoader(
            filter_text="",
            stub=self.root.package_stub,
            show_ros=ui.CBOPT1Search.isChecked(),
            show_python=ui.CBOPT2Search.isChecked(),
            show_rti=ui.CBRti.isChecked()
        )
        self.pkg_loader.package_received.connect(self.add_pkg_to_ui)
        self.pkg_loader.finished.connect(self._on_initial_load_finished)
        self.pkg_loader.start()

    def _clear_layout(self, layout):
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                else:
                    self._clear_layout(item.layout())

    def _on_packages_loaded(self, packages):
        import re
        from PySide6.QtCore import QCoreApplication
        from external.rqt2_widgets.utils.frame_option_button import FrameOptionButtonWidget
        from external.rqt2_widgets.utils.icon_loader import _resolve_icon
        
        ui = self.current_window.ui
        pattern = re.compile(r"^ros-(?P<distro>[a-z]+)-(?P<type>ros-core|desktop|desktop-full)$")
        
        distro_groups = {}
        for pkg in packages:
            name = pkg['name']
            match = pattern.match(name)
            if match:
                distro = match.group('distro')
                pkg_type = match.group('type')
                if distro not in distro_groups:
                    distro_groups[distro] = {}
                distro_groups[distro][pkg_type] = name
                
        distro_order = [
            "rolling", "bouncy", "crystal", "dashing", "eloquent", "foxy", "galactic",
            "humble", "iron", "jazzy", "kilted", "lyrical"
        ]

        distro_order.reverse()
        
        def distro_sort_key(distro_name):
            try:
                return distro_order.index(distro_name)
            except ValueError:
                return len(distro_order)
                
        sorted_distros = sorted(distro_groups.keys(), key=distro_sort_key)
        self.option_buttons = []
        
        type_cols = {
            'ros-core': 0,
            'desktop': 1,
            'desktop-full': 2
        }
        
        for row_idx, distro in enumerate(sorted_distros):
            types_found = distro_groups[distro]
            for pkg_type, col_idx in type_cols.items():
                if pkg_type in types_found:
                    pkg_name = types_found[pkg_type]
                    icon_name = 'ros-core' if pkg_type == 'ros-core' else ('ros-desktop' if pkg_type == 'desktop' else 'ros-full')
                    icon_path = _resolve_icon(self.root.icon_dirs, os.path.join(icon_name, 'default.svg'), theme=self.root.theme)
                    
                    if pkg_type == 'ros-core':
                        title_text = f"ROS2 {distro.capitalize()} Core"
                        info_text = QCoreApplication.translate("Widget", "Lo minimo necesario para funcionar", None)
                    elif pkg_type == 'desktop':
                        title_text = f"ROS2 {distro.capitalize()} Desktop"
                        info_text = QCoreApplication.translate("Widget", "Lo suficiente para empezar a trabajar", None)
                    else:
                        title_text = f"ROS2 {distro.capitalize()} Full"
                        info_text = QCoreApplication.translate("Widget", "Lo necesario para trabajar", None)
                        
                    btn = FrameOptionButtonWidget(
                        icon_path=icon_path,
                        title=title_text,
                        info=info_text,
                        parent=ui.scrollAreaWidgetContentsOptions,
                        theme=self.root.theme,
                        button_id=pkg_name
                    )
                    
                    ui.gridLayout_options.addWidget(btn, row_idx, col_idx, 1, 1)
                    self.option_buttons.append(btn)
                    btn.toggled.connect(lambda checked, b=btn: self._on_option_toggled(checked, b))
                    
        if self.option_buttons:
            default_btn = self.option_buttons[-1]
            for btn in self.option_buttons:
                if 'desktop-full' in btn.button_id:
                    default_btn = btn
            default_btn.setChecked(True)
            ui.BTNNext.setEnabled(True)

    def _on_option_toggled(self, checked, clicked_btn):
        if checked:
            for btn in self.option_buttons:
                if btn != clicked_btn:
                    btn.setChecked(False)
            self.selected_ros_package = clicked_btn.button_id
            self.current_window.setProperty("selected_ros_option", clicked_btn.button_id)
            if hasattr(self.current_window, "ui"):
                self.current_window.ui.BTNNext.setEnabled(True)

    def _on_table_clicked(self, index):
        if index.column() == 1:
            ui = self.current_window.ui
            row = index.row()
            if row >= 0 and row < len(ui.pkg_model._data):
                pkg = ui.pkg_model._data[row]
                pkg_name = pkg['name']
                if pkg.get('pending'):
                    self.pending_packages[pkg_name] = {
                        'name': pkg_name,
                        'installed': pkg.get('installed', False),
                        'pending': True
                    }
                else:
                    self.pending_packages.pop(pkg_name, None)

    def add_pkg_to_ui(self, pkg):
        if not self.current_window or self.current_step_idx != 2:
            return
        ui = self.current_window.ui
        model = ui.pkg_model
        row = model.rowCount()
        model.beginInsertRows(QModelIndex(), row, row)
        is_pending = pkg.name in self.pending_packages
        model._data.append({'name': pkg.name, 'installed': pkg.is_installed, 'pending': is_pending})
        model.endInsertRows()

    def _on_initial_load_finished(self):
        try:
            if self.current_window and self.current_step_idx == 2:
                ui = self.current_window.ui
                ui.EDITSearch.setEnabled(True)
                ui.EDITSearch.setPlaceholderText("Buscar paquetes...")
        except Exception:
            pass

    def on_search_changed(self, text):
        if hasattr(self, 'search_thread') and self.search_thread.isRunning():
            self.search_thread.cancel()
            self.search_thread.wait()
            
        self.search_timer.stop()
        self.search_timer.start(300)
        
        ui = self.current_window.ui
        ui.pkg_model.beginResetModel()
        ui.pkg_model._data = []
        ui.pkg_model.endResetModel()

    def _do_package_search(self):
        try:
            if not self.current_window or self.current_step_idx != 2:
                return
            ui = self.current_window.ui
            query = ui.EDITSearch.text()
            self.search_thread = PackageSearchThread(
                query,
                self.root.package_stub,
                show_ros=ui.CBOPT1Search.isChecked(),
                show_python=ui.CBOPT2Search.isChecked(),
                show_rti=ui.CBRti.isChecked()
            )
            self.search_thread.packages_received.connect(self.update_package_table)
            self.search_thread.start()
        except Exception:
            self.search_timer.stop()

    def update_package_table(self, packages):
        if not self.current_window or self.current_step_idx != 2:
            return
        ui = self.current_window.ui
        for pkg in packages:
            pkg['pending'] = pkg['name'] in self.pending_packages
        ui.pkg_model.beginResetModel()
        ui.pkg_model._data = packages
        ui.pkg_model.endResetModel()

    def _cleanup_step2(self):
        if hasattr(self, 'pkg_loader') and self.pkg_loader.isRunning():
            self.pkg_loader.cancel()
            self.pkg_loader.wait()
        if hasattr(self, 'search_thread') and self.search_thread.isRunning():
            self.search_thread.cancel()
            self.search_thread.wait()
        self.search_timer.stop()

    def _init_progress_step(self):
        ui = self.current_window.ui
        ui.BTNBack.setEnabled(False)
        ui.BTNNext.setEnabled(False)
        ui.BTNCancel.setEnabled(False)
        ui.progressBar.setRange(0, 1000)
        ui.progressBar.setValue(0)
        ui.LABELInstallProgress.setText("Preparando instalación...")
        ui.LABELConfigProgress.setText("")
        
        ui.CBLoadRosShell.setVisible(False)
        ui.CBConfigDomainId.setVisible(False)
        ui.LABELDomainId.setVisible(False)
        ui.spinBox.setVisible(False)

        self.install_queue = []
        if hasattr(self, 'selected_ros_package') and self.selected_ros_package:
            self.install_queue.append(self.selected_ros_package)

        if hasattr(self, 'pending_packages'):
            for pkg_name in self.pending_packages.keys():
                if pkg_name != getattr(self, 'selected_ros_package', None):
                    self.install_queue.append(pkg_name)

        self.total_pkgs = len(self.install_queue)
        self.current_pkg_idx = 0
        self._process_next_install()

    def _process_next_install(self):
        ui = self.current_window.ui
        if self.install_queue:
            self.current_pkg_idx += 1
            pkg_name = self.install_queue.pop(0)
            self.current_pkg_name = pkg_name
            self.current_dep = ""
            
            ui.progressBar.setRange(0, 1000)
            ui.progressBar.setValue(0)
            ui.LABELInstallProgress.setText(f"({self.current_pkg_idx}/{self.total_pkgs}) Instalando {pkg_name}...")
            ui.LABELConfigProgress.setText("")
            
            self.capturing_packages = False
            self.detected_packages = set()
            self.stage2_max = 300
            self.in_stage2 = False
            
            self.pkg_installer = PackageInstaller(pkg_name, self.root.package_stub)
            self.pkg_installer.log_received.connect(self._on_install_progress)
            self.pkg_installer.finished_ok.connect(self._on_install_finished)
            self.pkg_installer.start()
        else:
            ui.LABELInstallProgress.setText("Configurando entorno micro-ROS...")
            ui.progressBar.setRange(0, 100)
            ui.progressBar.setValue(0)
            ui.LABELConfigProgress.setText("")
            
            self.env_installer = EnvInstallWorker(self.root.installer_stub)
            self.env_installer.progress_updated.connect(self._on_env_progress)
            self.env_installer.finished.connect(self._on_env_finished)
            self.env_installer.start()

    def _on_install_progress(self, log_line, progress):
        import re
        ui = self.current_window.ui
        if not log_line:
            return
            
        log_line_strip = log_line.strip()
        ui.LABELConfigProgress.setText(log_line_strip[:60])
        log_lower = log_line_strip.lower()
        
        # 1. Parse current dependency (Y)
        dep = None
        des_match = re.search(r"(Des|Get):\d+\s+\S+\s+\S+\s+\S+\s+([a-z0-9\-_+\.:]+)", log_line_strip)
        if des_match:
            dep = des_match.group(2)
        else:
            sel_match = re.search(r"(Selecting previously unselected package|Seleccionando el paquete)\s+([a-z0-9\-_+\.:]+)", log_line_strip)
            if sel_match:
                dep = sel_match.group(2)
            else:
                desemp_match = re.search(r"(Preparing to unpack|Unpacking|Desempaquetando)\s+([a-z0-9\-_+\.:]+)", log_line_strip)
                if desemp_match:
                    dep = desemp_match.group(2)
                else:
                    conf_match = re.search(r"(Setting up|Configurando)\s+([a-z0-9\-_+\.:]+)", log_line_strip)
                    if conf_match:
                        dep = conf_match.group(2)
                        
        if dep:
            self.current_dep = dep
            
        action_verb = "Configurando" if self.in_stage2 else "Instalando"
        if self.current_dep:
            ui.LABELInstallProgress.setText(
                f"({self.current_pkg_idx}/{self.total_pkgs}) {action_verb} {self.current_pkg_name} ({self.current_dep})...."
            )
        else:
            ui.LABELInstallProgress.setText(
                f"({self.current_pkg_idx}/{self.total_pkgs}) {action_verb} {self.current_pkg_name}..."
            )
            
        # 2. Parse package count
        if ("instalando:" in log_lower or 
            "instalando dependencias:" in log_lower or 
            "siguientes paquetes nuevos" in log_lower or 
            "siguientes paquetes adicionales" in log_lower or
            "siguientes paquetes dependientes" in log_lower):
            self.capturing_packages = True
            return
            
        if ("paquetes sugeridos:" in log_lower or 
            "sugeridos:" in log_lower or 
            "resumen:" in log_lower or 
            "actualizados," in log_lower or 
            "necesita descargar" in log_lower):
            self.capturing_packages = False
            self.package_count = len(self.detected_packages)
            if self.package_count > 0:
                self.stage2_max = self.package_count * 3
            return
            
        if self.capturing_packages:
            words = [w.strip() for w in log_line_strip.split() if w.strip()]
            for w in words:
                if re.match(r"^[a-z0-9\-_+\.:]+$", w):
                    self.detected_packages.add(w)
                    
        # 3. Progress bar ranges logic
        is_install_action = ("selecting previously unselected package" in log_lower or
                             "selecting " in log_lower or
                             "seleccionando el paquete" in log_lower or 
                             "preparing to unpack" in log_lower or
                             "unpacking" in log_lower or
                             "desempaquetando" in log_lower or 
                             "setting up" in log_lower or
                             "configurando" in log_lower)

        if ("descargados" in log_lower or 
            "descargado " in log_lower or 
            "fetched " in log_lower or 
            "downloaded " in log_lower or
            (not self.in_stage2 and is_install_action)):
            
            if not self.in_stage2:
                self.in_stage2 = True
                ui.progressBar.setValue(0)
                ui.progressBar.setRange(0, self.stage2_max)
                
            if is_install_action:
                val = min(ui.progressBar.value() + 1, self.stage2_max)
                ui.progressBar.setValue(val)
            return
            
        if not self.in_stage2:
            if "des:" in log_lower or "get:" in log_lower:
                val = min(ui.progressBar.value() + 5, 999)
                ui.progressBar.setValue(val)
        else:
            if is_install_action:
                val = min(ui.progressBar.value() + 1, self.stage2_max)
                ui.progressBar.setValue(val)

    def _on_install_finished(self, pkg_name):
        self._process_next_install()

    def _on_env_progress(self, log_line, progress_percentage):
        ui = self.current_window.ui
        ui.progressBar.setRange(0, 100)
        ui.progressBar.setValue(progress_percentage)
        if log_line:
            ui.LABELConfigProgress.setText(log_line.strip()[:60])

    def _on_env_finished(self, success, error_msg):
        ui = self.current_window.ui
        ui.BTNCancel.setEnabled(True)
        
        if success:
            ui.LABELInstallProgress.setText("Instalación completada con éxito.")
            ui.progressBar.setRange(0, 100)
            ui.progressBar.setValue(100)
            ui.LABELConfigProgress.setText("")
            ui.CBLoadRosShell.setVisible(True)
            ui.CBConfigDomainId.setVisible(True)
            ui.LABELDomainId.setVisible(ui.CBConfigDomainId.isChecked())
            ui.spinBox.setVisible(ui.CBConfigDomainId.isChecked())
            ui.BTNNext.setEnabled(True)
        else:
            ui.LABELInstallProgress.setText("La instalación falló.")
            ui.LABELConfigProgress.setText(error_msg[:60] if error_msg else "Error desconocido.")
            ui.BTNBack.setEnabled(True)
            
            error_box = QMessageBox(self.current_window)
            error_box.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
            error_box.setIcon(QMessageBox.Icon.Critical)
            error_box.setWindowTitle("RQT2 | Error")
            error_box.setText("No se pudo completar la instalación")
            error_box.setInformativeText(error_msg if error_msg else "Error desconocido durante la instalación del entorno.")
            error_box.addButton("Aceptar", QMessageBox.ButtonRole.AcceptRole)
            error_box.exec()

    def _on_config_progress(self, log_line, progress_percentage):
        ui = self.current_window.ui
        ui.progressBar.setRange(0, 100)
        ui.progressBar.setValue(progress_percentage)
        ui.LABELInstallProgress.setText("Aplicando configuraciones de la shell...")
        if log_line:
            ui.LABELConfigProgress.setText(log_line.strip()[:60])

    def _on_config_finished(self, success, error_msg):
        ui = self.current_window.ui
        ui.BTNCancel.setEnabled(True)
        ui.BTNNext.setEnabled(True)
        ui.BTNBack.setEnabled(True)
        
        if success:
            if self.current_step_idx < len(self.steps) - 1:
                self.current_step_idx += 1
                self._show_step(self.current_step_idx)
        else:
            error_box = QMessageBox(self.current_window)
            error_box.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
            error_box.setIcon(QMessageBox.Icon.Critical)
            error_box.setWindowTitle("RQT2 | Error")
            error_box.setText("No se pudo aplicar la configuración")
            error_box.setInformativeText(error_msg if error_msg else "Error desconocido al configurar la shell.")
            error_box.addButton("Aceptar", QMessageBox.ButtonRole.AcceptRole)
            error_box.exec()

    def _load_colored_logo(self):
        try:
            ui = self.current_window.ui
            icon_dirs = self.root.icon_dirs
            from external.rqt2_widgets.utils.icon_loader import _resolve_icon
            logo_path = _resolve_icon(icon_dirs, "symbolic-color.svg")
            if not logo_path or not os.path.exists(logo_path):
                return
                
            with open(logo_path, "r", encoding="utf-8") as f:
                svg_content = f.read()
                
            accent_color = "#0090ff"
            theme_path = ""
            for d in icon_dirs:
                potential_theme = os.path.join(os.path.dirname(d), "styles", "themes", self.root.theme)
                if os.path.exists(potential_theme):
                    theme_path = potential_theme
                    break
                potential_theme_2 = os.path.join(d, "styles", "themes", self.root.theme)
                if os.path.exists(potential_theme_2):
                    theme_path = potential_theme_2
                    break
            
            if theme_path and os.path.exists(theme_path):
                try:
                    with open(theme_path, "r", encoding="utf-8") as tf:
                        theme_content = tf.read()
                        import re
                        m = re.search(r'"accent":\s*"([^"]+)"', theme_content)
                        if m:
                            accent_color = m.group(1)
                except Exception:
                    pass
                    
            import re
            svg_content = re.sub(r'fill\s*=\s*["\']#?[a-fA-F0-9]{6}["\']', f'fill="{accent_color}" stroke="none" stroke-width="0"', svg_content)
            
            from PySide6.QtCore import QByteArray
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtGui import QPainter, QPixmap
            
            renderer = QSvgRenderer(QByteArray(svg_content.encode("utf-8")))
            pixmap = QPixmap(256, 256)
            pixmap.fill(Qt.transparent)
            painter = QPainter(pixmap)
            painter.setPen(Qt.NoPen)
            renderer.render(painter)
            painter.end()
            
            ui.LABELLogo.setPixmap(pixmap)
            ui.LABELLogo.setScaledContents(True)
        except Exception as e:
            print(f"Error loading colored logo: {e}")
