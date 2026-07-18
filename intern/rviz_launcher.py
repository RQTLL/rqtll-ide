import os
from PySide6.QtCore import QObject, QSize
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QFrame, QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QSpacerItem, QSizePolicy
from PySide6.QtGui import QIcon
from external.rqtll_widgets.forms.g5_ui_rviz2 import Ui_Widget as Ui_G5

try:
    from external.rqtll_widgets.utils.icon_loader import _resolve_icon
except Exception:
    from rqtll_widgets.utils.icon_loader import _resolve_icon

class RvizLauncherController(QObject):
    def __init__(self, ide_controller):
        super().__init__()
        self.ide = ide_controller
        self.tabs = []
        self.is_gz_sim = False

    def bind(self, window):
        self.window = window
        self.ui = window.ui
        self.tab_widget = self.ui.tabWidget
        
        # Create spacer widget for the first tab
        self.ui.spacer_widget = QWidget(self.tab_widget.widget(0))
        spacer_layout = QHBoxLayout(self.ui.spacer_widget)
        spacer_layout.setContentsMargins(0, 0, 0, 0)
        spacer_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.ui.gridLayout.addWidget(self.ui.spacer_widget, 0, 1, 1, 1)
        
        self.show_text_edit(self.ui, False)
        
        self.ui.is_connected = False
        self.ui.tab_page = self.tab_widget.widget(0)
        self.tabs.append(self.ui)
        
        self.ui.BTNConnect.clicked.connect(lambda: self.on_connect_clicked(self.ui))
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

    def show_text_edit(self, ui_inst, show):
        if show:
            ui_inst.spacer_widget.hide()
            ui_inst.textEdit.show()
        else:
            ui_inst.textEdit.hide()
            ui_inst.spacer_widget.show()

    def get_display_name(self, ui_inst, idx):
        config_path = ui_inst.EDITConfig.text().strip()
        config_name = os.path.basename(config_path) if config_path else ""
        title_name = ui_inst.EDITTitle.text().strip()
        return config_name or title_name or f"Visualizaci\u00f3n {idx}"

    def on_connect_clicked(self, ui_inst):
        tab_idx = self.tab_widget.indexOf(ui_inst.tab_page)
        if tab_idx == -1:
            return

        connected = ui_inst.is_connected
        
        if not connected:
            ui_inst.is_connected = True
            
            icon = QIcon()
            icon_path = _resolve_icon(self.window._initial_icon_dirs, os.path.join('icons', 'synchronize', 'click.svg'), theme=self.window._initial_theme)
            icon.addFile(icon_path, QSize(), QIcon.Mode.Normal, QIcon.State.Off)
            ui_inst.BTNConnect.setIcon(icon)
            ui_inst.BTNConnect.setText("Desconectar")
            
            self.show_text_edit(ui_inst, True)
            
            server_name = self.get_display_name(ui_inst, tab_idx + 1)
            self.tab_widget.setTabText(tab_idx, server_name)
            
            has_plus = False
            for i in range(self.tab_widget.count()):
                if self.tab_widget.tabText(i) == "+":
                    has_plus = True
                    break
            if not has_plus:
                plus_tab = QWidget()
                self.tab_widget.addTab(plus_tab, "+")
        else:
            ui_inst.is_connected = False
            
            icon = QIcon()
            icon_path = _resolve_icon(self.window._initial_icon_dirs, os.path.join('icons', 'synchronize', 'default.svg'), theme=self.window._initial_theme)
            icon.addFile(icon_path, QSize(), QIcon.Mode.Normal, QIcon.State.Off)
            ui_inst.BTNConnect.setIcon(icon)
            ui_inst.BTNConnect.setText("Conectar")
            
            self.show_text_edit(ui_inst, False)
            
            last_idx = self.tab_widget.count() - 1
            if last_idx >= 0 and self.tab_widget.tabText(last_idx) == "+":
                self.tab_widget.removeTab(last_idx)
                
            self.tab_widget.setTabText(tab_idx, "+")

    def on_tab_changed(self, index):
        if index >= 0 and index < self.tab_widget.count():
            if self.tab_widget.tabText(index) == "+" and self.tab_widget.widget(index).layout() is None:
                self.tab_widget.setTabText(index, f"Visualizaci\u00f3n {index + 1}")
                self.initialize_tab_ui(index)

    def initialize_tab_ui(self, index):
        tab_widget = self.tab_widget.widget(index)
        if tab_widget.layout() is not None:
            return
            
        dummy = QWidget()
        ui_inst = Ui_G5()
        ui_inst.setupUi(dummy, icon_dirs=self.window._initial_icon_dirs, theme=self.window._initial_theme)
        
        grid_layout = QGridLayout(tab_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.addWidget(ui_inst.frame_2, 0, 0, 1, 1)
        grid_layout.addWidget(ui_inst.textEdit, 0, 1, 1, 1)
        
        ui_inst.spacer_widget = QWidget(tab_widget)
        spacer_layout = QHBoxLayout(ui_inst.spacer_widget)
        spacer_layout.setContentsMargins(0, 0, 0, 0)
        spacer_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        grid_layout.addWidget(ui_inst.spacer_widget, 0, 1, 1, 1)
        
        self.show_text_edit(ui_inst, False)
        
        ui_inst.is_connected = False
        ui_inst.tab_page = tab_widget
        self.tabs.append(ui_inst)
        
        ui_inst.BTNConnect.clicked.connect(lambda: self.on_connect_clicked(ui_inst))
