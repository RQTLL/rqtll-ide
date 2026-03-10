import packages_pb2
from PySide6.QtCore import QThread, Signal

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
        except Exception:
            pass

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
        except Exception:
            pass
        self.finished_ok.emit(self.package_name)
