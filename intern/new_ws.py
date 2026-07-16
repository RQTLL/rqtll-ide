import os
import workspace_pb2

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtWidgets import QLineEdit, QComboBox, QDoubleSpinBox, QScrollArea, QWidget, QLabel
from PySide6.QtCore import Qt

class NewWorkspaceController(QObject):
    def __init__(self, root_controller, clone_ws_controller, switch_to_ide_cb):
        super().__init__()
        self.root = root_controller
        self.clone_ws = clone_ws_controller
        self.switch_to_ide_cb = switch_to_ide_cb
        self.window = None

    def bind(self, window):
        self.window = window

        # Defaults for first render
        if not self.window.ui.EDITDir.text().strip():
            self.window.ui.EDITDir.setText(os.path.expanduser("~"))

        try:
            self.window.ui.BTNDir.clicked.disconnect()
        except Exception:
            pass
        self.window.ui.BTNDir.clicked.connect(self.select_destination_dir)

        try:
            self.window.ui.BTNMake.clicked.disconnect()
        except Exception:
            pass
        self.window.ui.BTNMake.clicked.connect(self.create_project)

        try:
            self.window.ui.EDITWSNew.textChanged.disconnect()
        except Exception:
            pass
        self.window.ui.EDITWSNew.textChanged.connect(self._update_make_button_state)

        try:
            self.window.ui.EDITDir.textChanged.disconnect()
        except Exception:
            pass
        self.window.ui.EDITDir.textChanged.connect(self._update_make_button_state)

        try:
            self.window.ui.BTNPKGNew.clicked.disconnect(self._on_pkg_added_or_changed)
        except Exception:
            pass
        self.window.ui.BTNPKGNew.clicked.connect(self._on_pkg_added_or_changed)

        try:
            self.window.ui.EDITPKGNew.returnPressed.disconnect(self._on_pkg_added_or_changed)
        except Exception:
            pass
        self.window.ui.EDITPKGNew.returnPressed.connect(self._on_pkg_added_or_changed)

        self._update_make_button_state()
        self._on_pkg_added_or_changed()

    def _on_pkg_added_or_changed(self):
        if not self.window:
            return
        for i in range(self.window.ui.TABPKGNew.count()):
            tab = self.window.ui.TABPKGNew.widget(i)
            if not tab:
                continue
            cb = tab.findChild(QComboBox, "CBPKGAment")
            group_node = tab.findChild(QWidget, "GROUPNode")
            group_launch = tab.findChild(QWidget, "GROUPLaunch")
            if cb and group_node and group_launch:
                if not cb.property("rqtll_connected"):
                    handler = self._make_ament_changed_handler(group_node, group_launch)
                    cb.currentIndexChanged.connect(handler)
                    cb.setProperty("rqtll_connected", True)
                    handler(cb.currentIndex())

    def _make_ament_changed_handler(self, group_node, group_launch):
        def handler(index):
            is_enabled = (index != 2)
            group_node.setEnabled(is_enabled)
            group_launch.setEnabled(is_enabled)
        return handler

    def _update_make_button_state(self):
        if self.window is None:
            return

        self.window.ui.BTNMake.setEnabled(bool(self.window.ui.EDITDir.text().strip()))

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

    def create_project(self):
        if self.window is None:
            return

		# workspace
        ws_name = self.window.ui.EDITWSNew.text().strip()
        destination_dir = self.window.ui.EDITDir.text().strip()

        if not ws_name:
            ws_name = "ros2_ws"

        base_dir = os.path.expanduser(destination_dir) if destination_dir else os.path.expanduser("~")
        final_target_dir = os.path.normpath(os.path.join(base_dir, ws_name))

        new_pkg = {}
        for pkg in range(self.window.ui.TABPKGNew.count()):
            widget = self.window.ui.TABPKGNew.widget(pkg)
            if not widget:
                continue
            
            new_pkg[self.window.ui.TABPKGNew.tabText(pkg)] = {
                "type": widget.findChild(QComboBox, "CBPKGAment").currentText(),
                "version": widget.findChild(QLineEdit, "EDITProjectVer").text().strip() if widget.findChild(QLineEdit, "EDITProjectVer") is not None else "0.0.0",
                "description": widget.findChild(QLineEdit, "EDITPKGDescription").text().strip(),
                "license": widget.findChild(QComboBox, "CBPKGLicense").currentText(),
                "dependencies": widget.findChild(QLineEdit, "EDITPKGApts").text().strip().split(' '),
                "maintainer": {
                    "name": widget.findChild(QLineEdit, "EDITMAINTName").text().strip(),
                    "email": widget.findChild(QLineEdit, "EDITMAINTEmail").text().strip() if '@' in widget.findChild(QLineEdit, "EDITMAINTEmail").text() else "",
                },
                "destination-dir": widget.findChild(QLineEdit, "EDITPKGDir").text().strip()
            }
            
            for i in range(widget.findChild(QScrollArea, "FRAMENODEAdded").widget().layout().count()):
                node_widget = widget.findChild(QScrollArea, "FRAMENODEAdded").widget().layout().itemAt(i).widget()
                if node_widget and isinstance(node_widget, QWidget):
                    node_name_label = node_widget.findChild(QLabel)
                    if node_name_label:
                        node_name = node_name_label.text().strip()
                        if node_name:
                            if "nodes" not in new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]:
                                new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["nodes"] = []
                            new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["nodes"].append(node_name)
                            
            for i in range(widget.findChild(QScrollArea, "FRAMELAUNCHAdd").widget().layout().count()):
                launch_widget = widget.findChild(QScrollArea, "FRAMELAUNCHAdd").widget().layout().itemAt(i).widget()
                if launch_widget and isinstance(launch_widget, QWidget):
                    launch_name_label = launch_widget.findChild(QLabel)
                    if launch_name_label:
                        launch_name = launch_name_label.text().strip()
                        if launch_name:
                            if "launchers" not in new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]:
                                new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["launchers"] = []
                            new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["launchers"].append(launch_name)
            
            new_pkg[self.window.ui.TABPKGNew.tabText(pkg)] = {k: v for k, v in new_pkg[self.window.ui.TABPKGNew.tabText(pkg)].items() if v}
            if "maintainer" in new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]:
                new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["maintainer"] = {k: v for k, v in new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["maintainer"].items() if v}
            if new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["maintainer"] == {}:
                del new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["maintainer"]
            if new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["dependencies"] == ['']:
                del new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["dependencies"]

        try:
            ws_req = workspace_pb2.CreateWorkspaceRequest(path=final_target_dir)
            status = self.root.workspace_stub.CreateWorkspace(ws_req)
            if not status.ok:
                self._show_error(f"No se pudo crear el directorio del espacio de trabajo:\n{status.message}")
                return
        except Exception as e:
            self._show_error(f"Error de comunicación gRPC al crear el espacio de trabajo: {e}")
            return

        for pkg_name, pkg_data in new_pkg.items():
            raw_type = pkg_data.get("type", "").lower()
            build_type = raw_type.split("[")[1].replace("]","")

            req_options = {
                "description": pkg_data.get("description", ""),
                "license": pkg_data.get("license", ""),
                "maintainer-email": pkg_data.get("maintainer", {}).get("email", ""),
                "maintainer-name": pkg_data.get("maintainer", {}).get("name", ""),
                "destination-directory": os.path.join(final_target_dir, "src"),
                "version": pkg_data.get("version", "0.0.1"),
            }
            deps = pkg_data.get("dependencies", [])
            if deps:
                req_options["dependencies"] = " ".join(deps)

            try:
                pkg_req = workspace_pb2.CreatePackageRequest(
                    workspace_path=final_target_dir,
                    name=pkg_name,
                    build_type=build_type,
                    options=req_options
                )
                status = self.root.workspace_stub.CreatePackage(pkg_req)
                if not status.ok:
                    self._show_error(f"No se pudo crear el paquete {pkg_name}:\n{status.message}")
                    return
            except Exception as e:
                self._show_error(f"Error de comunicación gRPC al crear el paquete {pkg_name}: {e}")
                return

            # Register nodes and launchers if it is not ament_cargo
            if build_type in ["ament_python", "ament_cmake"]:
                nodes = pkg_data.get("nodes", [])
                launchers = pkg_data.get("launchers", [])
                try:
                    nodes_req = workspace_pb2.CreateNodesAndLaunchersRequest(
                        workspace_path=final_target_dir,
                        package_name=pkg_name,
                        nodes=nodes,
                        launchers=launchers
                    )
                    status = self.root.workspace_stub.CreateNodesAndLaunchers(nodes_req)
                    if not status.ok:
                        self._show_error(f"No se pudo registrar los nodos/lanzadores del paquete {pkg_name}:\n{status.message}")
                        return
                except Exception as e:
                    self._show_error(f"Error de comunicación gRPC al registrar nodos/lanzadores del paquete {pkg_name}: {e}")
                    return

        if self.window:
            self.window.close()
        self.switch_to_ide_cb(final_target_dir)

    def _show_error(self, message):
        if self.window is None:
            return

        msg_box = QMessageBox(self.window)
        msg_box.setWindowTitle("RQTLL | Error")
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setText("No se pudo crear el espacio de trabajo")
        msg_box.setInformativeText(message)
        msg_box.exec()
