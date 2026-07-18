from PySide6.QtCore import QObject

class CompilerController(QObject):
    def __init__(self, ide_controller):
        super().__init__()
        self.ide = ide_controller

    def bind(self, window):
        self.window = window
        self.ui = window.ui
        print("CompilerController bound to view.")
