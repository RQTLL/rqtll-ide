from PySide6.QtCore import QObject

class SshController(QObject):
    def __init__(self, ide_controller):
        super().__init__()
        self.ide = ide_controller

    def bind(self, window):
        self.window = window
        self.ui = window.ui
        print("SshController bound to view.")
