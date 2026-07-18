import os
from PySide6.QtCore import QObject
from external.rqtll_widgets.forms.g1_ui_text_editor import Ui_Widget as Ui_G1
from external.rqtll_widgets.forms.g2_ui_compiler import Ui_Widget as Ui_G2
from external.rqtll_widgets.forms.g3_ui_twist_controller import Ui_Widget as Ui_G3
from external.rqtll_widgets.forms.g4_ui_ssh import Ui_Widget as Ui_G4
from external.rqtll_widgets.forms.g5_ui_rviz2 import Ui_Widget as Ui_G5
from external.rqtll_widgets.forms.g6_ui_gz_sim import Ui_Widget as Ui_G6
from external.rqtll_widgets.forms.g7_ui_rqt import Ui_Widget as Ui_G7
from external.rqtll_widgets.forms.g8_ui_package_manager import Ui_Widget as Ui_G8
from external.rqtll_widgets.utils.base_window import DemoWindow

from .code_editor import CodeEditorController
from .compiler import CompilerController
from .twist_controller import TwistController
from .ssh import SshController
from .rviz_launcher import RvizLauncherController
from .gz_launcher import GzLauncherController
from .rqt_launcher import RqtLauncherController
from .package_manager import PackageManagerController

class IDEController(QObject):
    def __init__(self, root_controller, ws_path):
        super().__init__()
        self.root = root_controller
        self.ws_path = ws_path
        self.current_window = None
        self.current_target = None
        
        # Instantiate sub-controllers
        self.controllers = {
            "Editor": CodeEditorController(self),
            "Lanzador": CompilerController(self),
            "Control": TwistController(self),
            "SSH": SshController(self),
            "RViz2": RvizLauncherController(self),
            "Gazebo": GzLauncherController(self),
            "rqt": RqtLauncherController(self),
            "Gestor de paquetes": PackageManagerController(self.root, None),
        }

        # Mapping targets to UI form classes
        self.target_forms = {
            "Editor": Ui_G1,
            "Lanzador": Ui_G2,
            "Control": Ui_G3,
            "SSH": Ui_G4,
            "RViz2": Ui_G5,
            "Gazebo": Ui_G6,
            "rqt": Ui_G7,
            "Gestor de paquetes": Ui_G8,
        }

    def start(self):
        self.switch_view("Editor")

    def switch_view(self, target):
        if target == self.current_target:
            return
        
        if target not in self.target_forms:
            print(f"Target {target} not recognized.")
            return

        ui_class = self.target_forms[target]
        controller = self.controllers[target]

        pos = None
        size = None
        if self.current_window:
            pos = self.current_window.pos()
            size = self.current_window.size()

        title = f"RQTLL IDE | {target} / {os.path.basename(self.ws_path)}"
        new_window = DemoWindow(ui_class, title=title, 
                                icon_dirs=self.root.icon_dirs, 
                                show_daemon=True, show_tab=False, 
                                theme=self.root.theme)
        
        self._bind_navigation(new_window)

        if hasattr(controller, "bind"):
            controller.bind(new_window)

        if pos and size:
            new_window.move(pos)
            new_window.resize(size)
        
        new_window.show()

        if self.current_window:
            self.current_window.close()

        self.current_window = new_window
        self.current_target = target

    def _bind_navigation(self, window):
        ui = window.ui
        try:
            ui.nav.code.clicked.connect(lambda: self.switch_view("Editor"))
            ui.nav.launch.clicked.connect(lambda: self.switch_view("Lanzador"))
            #ui.nav.graph.clicked.connect(lambda: self.switch_view("nodes"))
            ui.nav.teleop.clicked.connect(lambda: self.switch_view("Control"))
            ui.nav.ssh.clicked.connect(lambda: self.switch_view("SSH"))
            ui.nav.viz.clicked.connect(lambda: self.switch_view("RViz2"))
            ui.nav.sim.clicked.connect(lambda: self.switch_view("Gazebo"))
            ui.nav.widgets.clicked.connect(lambda: self.switch_view("rqt"))
            ui.nav.packages.clicked.connect(lambda: self.switch_view("Gestor de paquetes"))
        except AttributeError as e:
            print(f"Error binding navigation: {e}")
