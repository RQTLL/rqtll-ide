import sys
import os
import webbrowser
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtCore import Qt

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

class RQT2Controller:
    def __init__(self, icon_dirs=icon_dirs, theme="dark.qss"):
        self.theme = theme
        self.active_dialogs = []
        
        self.f0 = DemoWindow(Ui_F0, title="RQT2 IDE", icon_dirs=icon_dirs, theme=self.theme)
        self.setup_f0_connections()
        self.f0.show()

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
                if self.f0.ui.FRAMENew and not self.f0.ui.FRAMENew.isHidden():
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
                if self.f0.ui.FRAMEClone and not self.f0.ui.FRAMEClone.isHidden():
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
        self.f4.setAttribute(Qt.WA_DeleteOnClose) #

        def safe_enable():
            try:
                if trigger_button:
                    trigger_button.setEnabled(True)
            except RuntimeError:
                pass
        self.f4.ui.BTNCancell.clicked.connect(self.f4.close)
        self.f4.destroyed.connect(safe_enable)
    
        self.f4.show()
        self.active_dialogs.append(self.f4)

    def open_docs(self):
        webbrowser.open('https://www.google.com')

    def switch_to_ide(self, ws_path):
        for dialog in self.active_dialogs:
            if dialog and not dialog.isHidden():
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    base_path = os.path.dirname(os.path.abspath(__file__))
    comp_path = os.path.join(base_path, "external/rqt2_components")
    
    load_resources(app, comp_path)
    
    controller = RQT2Controller(icon_dirs=icon_dirs)
    sys.exit(app.exec())
