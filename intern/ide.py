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
            "code": CodeEditorController(self),
            "launch": CompilerController(self),
            "teleop": TwistController(self),
            "ssh": SshController(self),
            "3d": RvizLauncherController(self),
            "emulator": GzLauncherController(self),
            "widgets": RqtLauncherController(self),
            "package": PackageManagerController(self.root, None),
        }

        # Mapping targets to UI form classes
        self.target_forms = {
            "code": Ui_G1,
            "launch": Ui_G2,
            "teleop": Ui_G3,
            "ssh": Ui_G4,
            "3d": Ui_G5,
            "emulator": Ui_G6,
            "widgets": Ui_G7,
            "package": Ui_G8,
        }

    def start(self):
        self.switch_view("code")

    def switch_view(self, target):
        if target == self.current_target:
            return
        
        if target not in self.target_forms:
            print(f"Target {target} not recognized.")
            return

        ui_class = self.target_forms[target]
        controller = self.controllers[target]

        # Save current window geometry if available
        pos = None
        size = None
        if self.current_window:
            pos = self.current_window.pos()
            size = self.current_window.size()

        # Create new view window
        title = f"RQTLL IDE / {os.path.basename(self.ws_path)}"
        new_window = DemoWindow(ui_class, title=title, 
                                icon_dirs=self.root.icon_dirs, 
                                show_daemon=True, show_tab=True, 
                                theme=self.root.theme)
        
        # Connect navigation buttons in the new window
        self._bind_navigation(new_window)

        # Bind controller functionality to the new view
        if hasattr(controller, "bind"):
            controller.bind(new_window)

        # Position and show new window
        if pos and size:
            new_window.move(pos)
            new_window.resize(size)
        
        new_window.show()

        # Close and clean up old window
        if self.current_window:
            self.current_window.close()

        self.current_window = new_window
        self.current_target = target

    def _bind_navigation(self, window):
        ui = window.ui
        try:
            ui.nav.code.clicked.connect(lambda: self.switch_view("code"))
            ui.nav.launch.clicked.connect(lambda: self.switch_view("launch"))
            #ui.nav.graph.clicked.connect(lambda: self.switch_view("nodes"))
            ui.nav.teleop.clicked.connect(lambda: self.switch_view("teleop"))
            ui.nav.ssh.clicked.connect(lambda: self.switch_view("ssh"))
            ui.nav.viz.clicked.connect(lambda: self.switch_view("3d"))
            ui.nav.sim.clicked.connect(lambda: self.switch_view("emulator"))
            ui.nav.widgets.clicked.connect(lambda: self.switch_view("widgets"))
            ui.nav.packages.clicked.connect(lambda: self.switch_view("package"))
        except AttributeError as e:
            print(f"Error binding navigation: {e}")
