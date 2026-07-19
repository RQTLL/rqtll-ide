import sys, os, subprocess

base_path = os.path.dirname(os.path.abspath(__file__))
proto_py_path = os.path.join(base_path, "external", "rqtll_api", "py")
if proto_py_path not in sys.path:
    sys.path.insert(0, proto_py_path)

import grpc
import packages_pb2
import packages_pb2_grpc
import installer_pb2
import installer_pb2_grpc
import workspace_pb2
import workspace_pb2_grpc
import interactive_execution_pb2
import interactive_execution_pb2_grpc

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QFontDatabase, QIcon, QGuiApplication
from PySide6.QtCore import Qt

from intern.home import HomeController
from intern.package_manager import PackageManagerController
from intern.wizard import WizardController
try:
    from external.rqtll_widgets.utils.theme_manager import get_theme_manager
except Exception:
    try:
        from rqtll_widgets.utils.theme_manager import get_theme_manager
    except Exception:
        def get_theme_manager():
            return None

icon_dirs = [
    os.path.join(base_path, "external", "rqtll_components"),
    os.path.join(base_path, "external", "rqtll_components", "assets"),
    os.path.join(base_path, "external", "rqtll_components", "assets", "branding"),
    os.path.join(base_path, "external", "rqtll_components", "assets", "icons"),
    os.path.join(base_path, "external", "rqtll_components", "styles"),
    os.path.join(base_path, "external", "rqtll_components", "styles", "themes"),
    os.path.join(base_path, "external", "rqtll_widgets"),
]

def load_resources(app, components_path, theme="dark.qss"):
    fonts_path = os.path.join(components_path, "assets/fonts")
    for root, dirs, files in os.walk(fonts_path):
        for file in files:
            if file.endswith((".ttf", ".otf")):
                QFontDatabase.addApplicationFont(os.path.join(root, file))

    qss_file = os.path.join(components_path, f"styles/themes/{theme}")
    if os.path.exists(qss_file):
        with open(qss_file, "r") as f:
            app.setStyleSheet(f.read())

class RQTLLRoot:
    def __init__(self, theme="dark.qss"):
        self.theme = theme
        self.icon_dirs = icon_dirs
        self.current_notify_id = None
        
        self.channel = grpc.insecure_channel('127.0.0.1:50051')
        self.package_stub = packages_pb2_grpc.PackageServiceStub(self.channel)
        self.installer_stub = installer_pb2_grpc.ROSInstallerServiceStub(self.channel)
        self.workspace_stub = workspace_pb2_grpc.WorkspaceServiceStub(self.channel)
        self.execution_stub = interactive_execution_pb2_grpc.CommandExecutionServiceStub(self.channel)
        
        self.show_startup_notification()
        if not self.check_ros2_installed():
            self.wizard = WizardController(self)
            self.wizard.start()
        else:
            self.open_home()

    def check_ros2_installed(self) -> bool:
        try:
            request = packages_pb2.ListPackagesRequest(filter="ros-core")
            response_iter = self.package_stub.ListAvailablePackages(request)
            try:
                first_pkg = next(response_iter)
                distro = first_pkg.version if first_pkg.version else "Jazzy"
                if distro in ["Ninguna", "No detectada"]:
                    return False
                return True
            except StopIteration:
                return False
        except Exception:
            exit(1)

    def open_home(self):
        self.home = HomeController(self)
        self.pkg_manager = PackageManagerController(self, self.home.f0)

    def update_theme(self, theme: str):
        self.theme = theme

    def show_startup_notification(self):
        logo_path = os.path.join(base_path, "external/rqtll_components/assets/branding/logo.svg")
        
        try:
            request = packages_pb2.ListPackagesRequest(filter="ros-base")
            response_iter = self.package_stub.ListAvailablePackages(request)
            try:
                first_pkg = next(response_iter)
                distro = first_pkg.version if first_pkg.version else "Jazzy"
                if distro in ["Ninguna", "No detectada"]:
                    title = "RQTLL IDE"
                    msg = "Motor funcionando pero ROS 2 no está instalado."
                    icon = logo_path
                else:
                    title = "RQTLL IDE"
                    msg = f"Motor funcionando. ROS 2 {distro.capitalize()} listo."
                    icon = logo_path
            except StopIteration:
                title = "RQTLL IDE"
                msg = "Motor funcionando pero ROS 2 no está instalado."
                icon = logo_path
        except grpc.RpcError as e:
            title = "RQTLL Error"
            if e.code() == grpc.StatusCode.UNAVAILABLE:
                msg = "Motor no disponible. Verifica que rqtll.service esté funcionando. (systemctl status rqtll.service)"
            else:
                msg = f"Error de conexión con el backend: {e.details()}"
            icon = "dialog-error"
        except Exception as e:
            title = "RQTLL Error"
            msg = f"Error inesperado: {str(e)}"
            icon = "dialog-error"

        cmd = ['notify-send', '--app-name', 'RQTLL IDE', '--print-id', '--icon', icon, title, msg]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        self.current_notify_id, _ = process.communicate()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    theme = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark and "dark.qss" or "light.qss"
    components_path = os.path.join(os.path.dirname(__file__), "external/rqtll_components")
    load_resources(app, components_path, theme)

    def _on_color_scheme_changed(*args, **kwargs):
        global theme
        new_theme = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark and "dark.qss" or "light.qss"
        if new_theme != theme:
            load_resources(app, components_path, new_theme)
            theme = new_theme
            if 'root' in globals() and isinstance(globals().get('root'), RQTLLRoot):
                globals().get('root').update_theme(new_theme)
            try:
                tm = get_theme_manager()
                tm.themeChanged.emit(new_theme)
            except Exception:
                pass

    try:
        QGuiApplication.styleHints().colorSchemeChanged.connect(_on_color_scheme_changed)
    except Exception:
        pass
    root = RQTLLRoot(theme)
    sys.exit(app.exec())
