import sys, os, subprocess
import grpc
import packages_pb2
import packages_pb2_grpc

from PySide6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtCore import Qt

from intern.home import HomeController
from intern.package_manager import PackageManagerController

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

class RQT2Root:
    def __init__(self, theme="dark.qss"):
        self.theme = theme
        self.icon_dirs = icon_dirs
        self.current_notify_id = None
        
        self.channel = grpc.insecure_channel('127.0.0.1:50051')
        self.package_stub = packages_pb2_grpc.PackageServiceStub(self.channel)
        
        self.show_startup_notification()
        self.home = HomeController(self)
        self.pkg_manager = PackageManagerController(self, self.home.f0)

    def show_startup_notification(self):
        logo_path = os.path.join(base_path, "external/rqt2_components/assets/branding/logo.svg")
        
        try:
            request = packages_pb2.ListPackagesRequest(filter="ros-base")
            response_iter = self.package_stub.ListAvailablePackages(request)
            first_pkg = next(response_iter)
            distro = first_pkg.version if first_pkg.version else "Jazzy"
            
            title = "RQT2 IDE"
            msg = f"Motor funcionando. ROS 2 {distro} listo."
            icon = logo_path
        except Exception:
            title = "RQT2 Error"
            msg = "Backend offline. Verifica el servidor de Rust."
            icon = "dialog-error"

        cmd = ['notify-send', '--app-name', 'RQT2 IDE', '--print-id', '--icon', icon, title, msg]
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
        self.current_notify_id, _ = process.communicate()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    load_resources(app, os.path.join(os.path.dirname(__file__), "external/rqt2_components"))
    root = RQT2Root()
    sys.exit(app.exec())
