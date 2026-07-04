import grpc
from PySide6.QtCore import QThread, Signal
import installer_pb2
import packages_pb2

class PackageListWorker(QThread):
    packages_received = Signal(list)

    def __init__(self, stub):
        super().__init__()
        self.stub = stub

    def run(self):
        try:
            request = packages_pb2.ListPackagesRequest(filter="(ros-core|desktop)")
            stream = self.stub.ListAvailablePackages(request)
            pkgs = []
            for response in stream:
                pkgs.append({
                    'name': response.name,
                    'description': response.description,
                    'is_installed': response.is_installed,
                    'version': response.version
                })
            self.packages_received.emit(pkgs)
        except Exception as e:
            print(f"Error fetching packages: {e}")
            self.packages_received.emit([])

class RepoSetupWorker(QThread):
    finished = Signal(bool, str)

    def __init__(self, root):
        super().__init__()
        self.root = root
        self.stub = root.installer_stub
        self.last_notify_time = 0.0

    def _send_dynamic_notification(self, title, msg, icon=None, progress=None, force=False):
        import time
        import subprocess
        now = time.time()
        if not force and progress is not None and progress < 100 and progress > 0:
            if now - self.last_notify_time < 0.3:
                return
        self.last_notify_time = now

        cmd = ['notify-send', '--app-name', 'RQT2 IDE', '--print-id', title, msg]
        if icon:
            cmd.extend(['--icon', icon])
        if progress is not None:
            cmd.extend(['-h', f'int:value:{int(progress)}'])
        if self.root.current_notify_id:
            cmd.extend(['--replace-id', self.root.current_notify_id.strip()])
        
        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
            self.root.current_notify_id, _ = process.communicate()
        except Exception:
            pass

    def run(self):
        try:
            request = installer_pb2.EnvInstallRequest()
            stream = self.stub.SetupRepositories(request)
            for response in stream:
                if response.status == installer_pb2.StepStatus.FAILED:
                    self._send_dynamic_notification(
                        "Configuración fallida", 
                        response.log_line, 
                        icon="dialog-error", 
                        force=True
                    )
                    self.finished.emit(False, response.log_line)
                    return
                
                self._send_dynamic_notification(
                    "Configurando ROS2",
                    response.log_line,
                    progress=response.progress_percentage
                )
            
            self._send_dynamic_notification(
                "Configuración completada",
                "Repositorios configurados con éxito.",
                progress=100,
                force=True
            )
            self.finished.emit(True, "")
        except grpc.RpcError as e:
            self.finished.emit(False, f"Error de gRPC: {e.details()}")
        except Exception as e:
            self.finished.emit(False, str(e))

class EnvInstallWorker(QThread):
    progress_updated = Signal(str, int)
    finished = Signal(bool, str)

    def __init__(self, stub):
        super().__init__()
        self.stub = stub

    def run(self):
        try:
            request = installer_pb2.EnvInstallRequest()
            stream = self.stub.InstallEnvironment(request)
            for response in stream:
                if response.status == installer_pb2.StepStatus.FAILED:
                    self.finished.emit(False, response.log_line)
                    return
                self.progress_updated.emit(response.log_line, response.progress_percentage)
            self.finished.emit(True, "")
        except grpc.RpcError as e:
            self.finished.emit(False, f"Error de gRPC: {e.details()}")
        except Exception as e:
            self.finished.emit(False, str(e))

class ConfigureEnvWorker(QThread):
    progress_updated = Signal(str, int)
    finished = Signal(bool, str)

    def __init__(self, stub, load_ros_shell, config_domain_id, domain_id, ros_distro):
        super().__init__()
        self.stub = stub
        self.load_ros_shell = load_ros_shell
        self.config_domain_id = config_domain_id
        self.domain_id = domain_id
        self.ros_distro = ros_distro

    def run(self):
        try:
            request = installer_pb2.ConfigureEnvRequest(
                load_ros_shell=self.load_ros_shell,
                config_domain_id=self.config_domain_id,
                domain_id=self.domain_id,
                ros_distro=self.ros_distro
            )
            stream = self.stub.ConfigureEnvironment(request)
            for response in stream:
                if response.status == installer_pb2.StepStatus.FAILED:
                    self.finished.emit(False, response.log_line)
                    return
                self.progress_updated.emit(response.log_line, response.progress_percentage)
            self.finished.emit(True, "")
        except grpc.RpcError as e:
            self.finished.emit(False, f"Error de gRPC: {e.details()}")
        except Exception as e:
            self.finished.emit(False, str(e))
