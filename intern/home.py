import os, webbrowser
from PySide6.QtWidgets import QFileDialog
from PySide6.QtCore import Qt, QObject
from external.rqt2_widgets.forms.f0_ui_main import Ui_Widget as Ui_F0
from external.rqt2_widgets.forms.f1_ui_new_ws import Ui_Widget as Ui_F1
from external.rqt2_widgets.forms.f3_ui_clone_ws import Ui_Widget as Ui_F3
from external.rqt2_widgets.forms.ui_form import Ui_Widget as Ui_Form
from external.rqt2_widgets.utils.base_window import DemoWindow
from .clone_ws import CloneWorkspaceController

class HomeController(QObject):
    def __init__(self, root_controller):
        super().__init__()
        self.root = root_controller
        self.clone_ws = CloneWorkspaceController(self.root, current_notify_id=self.root.current_notify_id)
        self.active_dialogs = []
        
        self.f0 = DemoWindow(Ui_F0, title="RQT2 IDE", 
                             icon_dirs=self.root.icon_dirs, 
                             theme=self.root.theme)
        self._setup_connections()
        try:
            self.f0.uiReinitialized.connect(self._setup_connections)
        except Exception:
            pass
        self.f0.show()

    def _setup_connections(self):
        self.f0.ui.FRAMENew.clicked.connect(self.open_f1)
        self.f0.ui.FRAMEOpen.clicked.connect(self.open_file_dialog)
        self.f0.ui.FRAMEClone.clicked.connect(self.open_f3)
        self.f0.ui.NAVInstall.clicked.connect(
            lambda: self.root.pkg_manager.open(trigger_button=self.f0.ui.NAVInstall)
        )
        self.f0.ui.NAVDocs.clicked.connect(lambda: webbrowser.open('https://www.google.com'))

    def open_f1(self):
        self.f1 = DemoWindow(Ui_F1, title="Nuevo espacio", 
                             icon_dirs=self.root.icon_dirs, 
                             parent=self.f0, theme=self.root.theme)
        self.f1.setAttribute(Qt.WA_DeleteOnClose)
        self.f0.ui.FRAMENew.setEnabled(False)
        try:
            self.f1.uiReinitialized.connect(lambda: None)
        except Exception:
            pass
        self.f1.ui.BTNCancell.clicked.connect(self.f1.close)
        self.f1.destroyed.connect(lambda: self.f0.ui.FRAMENew.setEnabled(True))
        self.f1.ui.BTNMake.clicked.connect(lambda: self.switch_to_ide("Nuevo"))
        self.f1.show()
        self.active_dialogs.append(self.f1)

    def open_f3(self):
        self.f3 = DemoWindow(Ui_F3, title="Clonar espacio", 
                             icon_dirs=self.root.icon_dirs, 
                             parent=self.f0, theme=self.root.theme)
        self.f3.setAttribute(Qt.WA_DeleteOnClose)
        self.f0.ui.FRAMEClone.setEnabled(False)
        try:
            self.f3.uiReinitialized.connect(lambda: None)
        except Exception:
            pass
        self.f3.ui.BTNCancell.clicked.connect(self.f3.close)
        self.f3.destroyed.connect(lambda: self.f0.ui.FRAMEClone.setEnabled(True))
        self.clone_ws.bind(self.f3)
        self.f3.show()
        self.active_dialogs.append(self.f3)

    def open_file_dialog(self):
        path = QFileDialog.getExistingDirectory(self.f0, "Cargar Espacio de Trabajo")
        if path: self.switch_to_ide(path)

    def switch_to_ide(self, ws_path):
        for dialog in self.active_dialogs:
            if dialog:
                if not dialog.isHidden(): 
                    dialog.close()
        
        self.f0.close()
        self.main_ide = DemoWindow(Ui_Form, title=f"RQT2 IDE / {os.path.basename(ws_path)}", 
                                   icon_dirs=self.root.icon_dirs, 
                                   show_daemon=True, show_tab=True, theme=self.root.theme)
        try:
            self.main_ide.uiReinitialized.connect(lambda: None)
        except Exception:
            pass
        self.main_ide.show()
