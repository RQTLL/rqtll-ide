import os

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

        self._update_make_button_state()

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
                
            if new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["type"] in ["Python (ament_python)", "C++ (ament_cmake)"]:
                new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["type"] = new_pkg[self.window.ui.TABPKGNew.tabText(pkg)]["type"].split(' ')[0].lower()

        # backend call to create the project
        # ok, message = self.clone_ws...
        """"
        if not ok:
            self._show_error(
                "No se pudo registrar el directorio en backend.\n"
                f"{message or 'Error desconocido'}"
            )
            return

        self.switch_to_ide_cb(final_target_dir)
        """

    def _show_error(self, message):
        if self.window is None:
            return

        msg_box = QMessageBox(self.window)
        msg_box.setWindowTitle("RQT2 | Error")
        msg_box.setIcon(QMessageBox.Icon.Critical)
        msg_box.setText("No se pudo crear el espacio de trabajo")
        msg_box.setInformativeText(message)
        msg_box.exec()
