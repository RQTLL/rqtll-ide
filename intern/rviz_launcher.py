import os, subprocess, re
from PySide6.QtCore import QObject, QSize, QThread, Signal, Qt, QTimer
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QFrame, QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QSpacerItem, QSizePolicy, QFileDialog
from PySide6.QtGui import QIcon, QTextCursor
from external.rqtll_widgets.forms.g5_ui_rviz2 import Ui_Widget as Ui_G5

import types_pb2
import interactive_execution_pb2
import interactive_execution_pb2_grpc

try:
    from external.rqtll_widgets.utils.icon_loader import _resolve_icon
except Exception:
    from rqtll_widgets.utils.icon_loader import _resolve_icon


class ExecutionOutputThread(QThread):
    output_received = Signal(str)
    session_finished = Signal()

    def __init__(self, stub, request):
        super().__init__()
        self.stub = stub
        self.request = request
        self.is_running = True

    def run(self):
        try:
            response_stream = self.stub.StartSession(self.request)
            for output in response_stream:
                if not self.is_running:
                    break
                text = output.data.decode('utf-8', errors='replace')
                self.output_received.emit(text)
        except Exception as e:
            print(f"Error in execution thread: {e}")
        finally:
            self.session_finished.emit()

    def stop(self):
        self.is_running = False


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
        
        # Apply clean monospace font to terminal
        self.setup_terminal_font(self.ui.textEdit)
        self.show_text_edit(self.ui, False)
        
        # Stop any active threads from the previous window binding
        if hasattr(self, "tabs") and self.tabs:
            for ui_inst in self.tabs:
                if ui_inst and hasattr(ui_inst, "thread") and ui_inst.thread:
                    try:
                        ui_inst.thread.stop()
                    except Exception:
                        pass

        self.ui.is_connected = False
        self.ui.tab_page = self.tab_widget.widget(0)
        self.ui.session_id = f"{self.ide.ws_path}_rviz2_0"
        self.ui.textEdit.setReadOnly(True)
        self.tabs = [self.ui]
        
        self.setup_ui_interactions(self.ui)
        self.setup_refresh_timer(self.ui)
        
        self.ui.BTNConnect.clicked.connect(lambda: self.on_connect_clicked(self.ui))
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        # Restore active sessions from backend
        self.restore_active_sessions()

    def setup_terminal_font(self, text_edit):
        font = text_edit.font()
        font.setFamily("UbuntuMono Nerd Font Mono")
        font.setStyleHint(font.StyleHint.Monospace)
        text_edit.setFont(font)

    def setup_refresh_timer(self, ui_inst):
        ui_inst.refresh_timer = QTimer(self)
        ui_inst.refresh_timer.setSingleShot(True)
        ui_inst.refresh_timer.timeout.connect(lambda u=ui_inst: self.refresh_terminal_view(u))
        ui_inst.pending_update = False
        ui_inst.terminal_buffer = ""

    def show_text_edit(self, ui_inst, show):
        if show:
            ui_inst.spacer_widget.hide()
            ui_inst.textEdit.show()
        else:
            ui_inst.textEdit.hide()
            ui_inst.spacer_widget.show()

    def get_display_name(self, ui_inst, idx):
        try:
            config_path = ui_inst.EDITConfig.text().strip()
            config_name = os.path.basename(config_path) if config_path else ""
            title_name = ui_inst.EDITTitle.text().strip()
            return config_name or title_name or f"Visualización {idx}"
        except Exception:
            return f"Visualización {idx}"

    def setup_ui_interactions(self, ui_inst):
        # File selectors for config and splash screen image
        def select_config_file(ui):
            path, _ = QFileDialog.getOpenFileName(
                self.window, 
                "Seleccionar archivo de configuración RViz2", 
                self.ide.ws_path, 
                "Archivos de configuración (*.rviz);;Todos los archivos (*)"
            )
            if path:
                ui.EDITConfig.setText(path)

        def select_splash_image(ui):
            path, _ = QFileDialog.getOpenFileName(
                self.window, 
                "Seleccionar imagen de splash", 
                self.ide.ws_path, 
                "Imágenes (*.png *.jpg *.jpeg *.svg);;Todos los archivos (*)"
            )
            if path:
                ui.EDITSplashScreen.setText(path)

        ui_inst.BTNConfig.clicked.connect(lambda: select_config_file(ui_inst))
        ui_inst.BTNSplashFile.clicked.connect(lambda: select_splash_image(ui_inst))

    def on_connect_clicked(self, ui_inst):
        try:
            tab_idx = self.tab_widget.indexOf(ui_inst.tab_page)
        except Exception:
            return
        if tab_idx == -1:
            return

        connected = ui_inst.is_connected
        
        if not connected:
            try:
                kwargs = {}
                
                # title
                val = ui_inst.EDITTitle.text().strip()
                if val:
                    kwargs["title"] = val
                    
                # config path
                val = ui_inst.EDITConfig.text().strip()
                if val:
                    kwargs["config_path"] = val
                    
                # fixed frame
                val = ui_inst.EDITFrame.text().strip()
                if val:
                    kwargs["fixed_frame"] = val
                    
                # splash screen image path
                val = ui_inst.EDITSplashScreen.text().strip()
                if val:
                    kwargs["image_path"] = val
                    
                # fullscreen
                if ui_inst.CHECKFulllscreen.isChecked():
                    kwargs["fullscreen"] = True
                    
                # log (Ogre log)
                if ui_inst.CHECKOgre.isChecked():
                    kwargs["log"] = True
                    
                rviz_req = interactive_execution_pb2.Rviz2Request(**kwargs)
                
                req_obj = interactive_execution_pb2.ExecutionRequest(
                    session_id=ui_inst.session_id,
                    rviz2=rviz_req
                )
                
                ui_inst.terminal_buffer = ""
                ui_inst.textEdit.clear()
                
                ui_inst.thread = ExecutionOutputThread(self.ide.root.execution_stub, req_obj)
                ui_inst.thread.output_received.connect(lambda text, u=ui_inst: self.append_to_terminal(u, text))
                ui_inst.thread.session_finished.connect(lambda u=ui_inst: self.on_session_finished(u))
                ui_inst.thread.start()
            except Exception as e:
                cmd = ['notify-send', '--app-name', 'RQTLL IDE', '--print-id',
                        '--icon', "edit-delete",
                        'Error de RViz2',
                        f'No se pudo iniciar RViz2: {e}']
                if self.ide.root.current_notify_id:
                    cmd.extend(['--replace-id', self.ide.root.current_notify_id.strip()])
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
                self.ide.root.current_notify_id, _ = process.communicate()
                return

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
            try:
                control_req = interactive_execution_pb2.ExecutionControl(
                    session_id=ui_inst.session_id,
                    action=interactive_execution_pb2.ExecutionControl.Action.STOP
                )
                self.ide.root.execution_stub.ControlSession(control_req)
            except Exception as e:
                print(f"Error stopping session: {e}")
                
            if hasattr(ui_inst, "thread") and ui_inst.thread:
                ui_inst.thread.stop()

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
                if last_idx < len(self.tabs):
                    self.tabs[last_idx] = None
                
            self.tab_widget.setTabText(tab_idx, "+")

    def append_to_terminal(self, ui_inst, text):
        clean_text = re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', text)
        clean_text = re.sub(r'\x1b\(.', '', clean_text)
        
        if not hasattr(ui_inst, "terminal_buffer"):
            ui_inst.terminal_buffer = ""
            
        ui_inst.terminal_buffer += clean_text
        
        lines = ui_inst.terminal_buffer.splitlines()
        if len(lines) > 1000:
            ui_inst.terminal_buffer = "\n".join(lines[-1000:]) + "\n"
            
        if not getattr(ui_inst, "pending_update", False):
            ui_inst.pending_update = True
            ui_inst.refresh_timer.start(30)

    def refresh_terminal_view(self, ui_inst):
        ui_inst.pending_update = False
        ui_inst.textEdit.setPlainText(getattr(ui_inst, "terminal_buffer", ""))
        
        cursor = ui_inst.textEdit.textCursor()
        cursor.movePosition(QTextCursor.End)
        ui_inst.textEdit.setTextCursor(cursor)
        
        scrollbar = ui_inst.textEdit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_session_finished(self, ui_inst):
        if getattr(ui_inst, "pending_update", False):
            ui_inst.refresh_timer.stop()
            self.refresh_terminal_view(ui_inst)
        if ui_inst.is_connected:
            cmd = ['notify-send', '--app-name', 'RQTLL IDE', '--print-id',
                    '--icon', "edit-delete",
                    'Sesión de RViz2 Detenida',
                    f'RViz2 {self.get_display_name(ui_inst, 1)} se ha desconectado.']
            if self.ide.root.current_notify_id:
                cmd.extend(['--replace-id', self.ide.root.current_notify_id.strip()])
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
            self.ide.root.current_notify_id, _ = process.communicate()
            self.on_connect_clicked(ui_inst)

    def on_tab_changed(self, index):
        if index >= 0 and index < self.tab_widget.count():
            if self.tab_widget.tabText(index) == "+" and self.tab_widget.widget(index).layout() is None:
                self.tab_widget.setTabText(index, f"Visualización {index + 1}")
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
        
        self.setup_terminal_font(ui_inst.textEdit)
        self.show_text_edit(ui_inst, False)
        
        ui_inst.is_connected = False
        ui_inst.tab_page = tab_widget
        ui_inst.session_id = f"{self.ide.ws_path}_rviz2_{index}"
        ui_inst.textEdit.setReadOnly(True)
        
        while len(self.tabs) <= index:
            self.tabs.append(None)
        self.tabs[index] = ui_inst
        
        self.setup_ui_interactions(ui_inst)
        self.setup_refresh_timer(ui_inst)
        
        ui_inst.BTNConnect.clicked.connect(lambda: self.on_connect_clicked(ui_inst))

    def restore_active_sessions(self):
        try:
            req = types_pb2.Empty()
            res = self.ide.root.execution_stub.GetActiveSessions(req)
            active_rviz = [s for s in res.sessions if s.HasField("rviz2")]
            
            for session in active_rviz:
                parts = session.session_id.split('_')
                try:
                    idx = int(parts[-1])
                except ValueError:
                    continue
                
                while self.tab_widget.count() <= idx:
                    new_tab = QWidget()
                    self.tab_widget.addTab(new_tab, f"Visualización {self.tab_widget.count() + 1}")
                
                while len(self.tabs) <= idx:
                    self.tabs.append(None)
                if self.tabs[idx] is None:
                    self.initialize_tab_ui(idx)
                
                ui_inst = self.tabs[idx]
                ui_inst.session_id = session.session_id
                
                rviz_data = session.rviz2
                ui_inst.EDITTitle.setText(rviz_data.title)
                ui_inst.EDITConfig.setText(rviz_data.config_path)
                ui_inst.EDITFrame.setText(rviz_data.fixed_frame)
                ui_inst.EDITSplashScreen.setText(rviz_data.image_path)
                ui_inst.CHECKFulllscreen.setChecked(rviz_data.fullscreen)
                ui_inst.CHECKOgre.setChecked(rviz_data.log)
                
                ui_inst.is_connected = True
                
                icon = QIcon()
                icon_path = _resolve_icon(self.window._initial_icon_dirs, os.path.join('icons', 'synchronize', 'click.svg'), theme=self.window._initial_theme)
                icon.addFile(icon_path, QSize(), QIcon.Mode.Normal, QIcon.State.Off)
                ui_inst.BTNConnect.setIcon(icon)
                ui_inst.BTNConnect.setText("Desconectar")
                
                self.show_text_edit(ui_inst, True)
                self.tab_widget.setTabText(idx, self.get_display_name(ui_inst, idx + 1))
                
                req_obj = interactive_execution_pb2.ExecutionRequest(
                    session_id=ui_inst.session_id,
                    rviz2=rviz_data
                )
                ui_inst.thread = ExecutionOutputThread(self.ide.root.execution_stub, req_obj)
                ui_inst.thread.output_received.connect(lambda text, u=ui_inst: self.append_to_terminal(u, text))
                ui_inst.thread.session_finished.connect(lambda u=ui_inst: self.on_session_finished(u))
                ui_inst.thread.start()
                
            if active_rviz:
                has_plus = False
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.tabText(i) == "+":
                        has_plus = True
                        break
                if not has_plus:
                    plus_tab = QWidget()
                    self.tab_widget.addTab(plus_tab, "+")
        except Exception as e:
            print(f"Error restoring active rviz sessions: {e}")
