import os, subprocess, re
from PySide6.QtCore import QObject, QSize, QThread, Signal, Qt, QTimer
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QFrame, QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QSpacerItem, QSizePolicy, QFileDialog
from PySide6.QtGui import QIcon, QTextCursor
from external.rqtll_widgets.forms.g7_ui_rqt import Ui_Widget as Ui_G7

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


class RqtLauncherController(QObject):
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
        self.ui.session_id = f"{self.ide.ws_path}_rqt_0"
        self.ui.textEdit.setReadOnly(True)
        self.tabs = [self.ui]
        
        self.setup_ui_interactions(self.ui)
        self.clear_combobox_selections(self.ui)
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
            perspective_name = ui_inst.EditPerspectivename.text().strip()
            perspective_file = ui_inst.EDITPerspectiveFile.text().strip()
            standalone_mode = ui_inst.OPTStandalone.currentIndex() > 0
            
            if standalone_mode:
                return ui_inst.OPTStandalone.currentText().strip()
            return perspective_name or os.path.basename(perspective_file) or f"Rqt {idx}"
        except Exception:
            return f"Rqt {idx}"

    def clear_combobox_selections(self, ui_inst):
        ui_inst.OPTStandalone.setCurrentIndex(-1)

    def setup_ui_interactions(self, ui_inst):
        # File selector for perspective file
        def select_perspective_file(ui):
            path, _ = QFileDialog.getOpenFileName(
                self.window, 
                "Seleccionar archivo de perspectiva Rqt", 
                self.ide.ws_path, 
                "Archivos de perspectiva (*.perspective);;Todos los archivos (*)"
            )
            if path:
                ui.EDITPerspectiveFile.setText(path)

        ui_inst.BTNPerspectiveFile.clicked.connect(lambda: select_perspective_file(ui_inst))

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
                
                # standalone or perspective name
                if ui_inst.OPTStandalone.currentIndex() > 0:
                    kwargs["perspective"] = f"standalone:{ui_inst.OPTStandalone.currentText().strip()}"
                else:
                    val = ui_inst.EditPerspectivename.text().strip()
                    if val:
                        kwargs["perspective"] = val
                        
                # perspective file
                val = ui_inst.EDITPerspectiveFile.text().strip()
                if val:
                    kwargs["perspective_file"] = val
                    
                # lock gui flag (ht)
                if ui_inst.CHECKhtfl.isChecked():
                    kwargs["ht"] = True
                    
                rqt_req = interactive_execution_pb2.RqtRequest(**kwargs)
                
                req_obj = interactive_execution_pb2.ExecutionRequest(
                    session_id=ui_inst.session_id,
                    rqt=rqt_req
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
                        'Error de Rqt',
                        f'No se pudo iniciar Rqt: {e}']
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
                    'Sesión de Rqt Detenida',
                    f'Rqt {self.get_display_name(ui_inst, 1)} se ha desconectado.']
            if self.ide.root.current_notify_id:
                cmd.extend(['--replace-id', self.ide.root.current_notify_id.strip()])
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
            self.ide.root.current_notify_id, _ = process.communicate()
            self.on_connect_clicked(ui_inst)

    def on_tab_changed(self, index):
        if index >= 0 and index < self.tab_widget.count():
            if self.tab_widget.tabText(index) == "+" and self.tab_widget.widget(index).layout() is None:
                self.tab_widget.setTabText(index, f"Rqt {index + 1}")
                self.initialize_tab_ui(index)

    def initialize_tab_ui(self, index):
        tab_widget = self.tab_widget.widget(index)
        if tab_widget.layout() is not None:
            return
            
        dummy = QWidget()
        ui_inst = Ui_G7()
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
        ui_inst.session_id = f"{self.ide.ws_path}_rqt_{index}"
        ui_inst.textEdit.setReadOnly(True)
        
        while len(self.tabs) <= index:
            self.tabs.append(None)
        self.tabs[index] = ui_inst
        
        self.setup_ui_interactions(ui_inst)
        self.clear_combobox_selections(ui_inst)
        self.setup_refresh_timer(ui_inst)
        
        ui_inst.BTNConnect.clicked.connect(lambda: self.on_connect_clicked(ui_inst))

    def restore_active_sessions(self):
        try:
            req = types_pb2.Empty()
            res = self.ide.root.execution_stub.GetActiveSessions(req)
            active_rqt = [s for s in res.sessions if s.HasField("rqt")]
            
            for session in active_rqt:
                parts = session.session_id.split('_')
                try:
                    idx = int(parts[-1])
                except ValueError:
                    continue
                
                while self.tab_widget.count() <= idx:
                    new_tab = QWidget()
                    self.tab_widget.addTab(new_tab, f"Rqt {self.tab_widget.count() + 1}")
                
                while len(self.tabs) <= idx:
                    self.tabs.append(None)
                if self.tabs[idx] is None:
                    self.initialize_tab_ui(idx)
                
                ui_inst = self.tabs[idx]
                ui_inst.session_id = session.session_id
                
                rqt_data = session.rqt
                if rqt_data.perspective.startswith("standalone:"):
                    standalone_val = rqt_data.perspective[len("standalone:"):]
                    for i in range(ui_inst.OPTStandalone.count()):
                        if ui_inst.OPTStandalone.itemText(i).strip() == standalone_val.strip():
                            ui_inst.OPTStandalone.setCurrentIndex(i)
                            break
                    ui_inst.EditPerspectivename.clear()
                else:
                    ui_inst.EditPerspectivename.setText(rqt_data.perspective)
                    ui_inst.OPTStandalone.setCurrentIndex(-1)
                    
                ui_inst.EDITPerspectiveFile.setText(rqt_data.perspective_file)
                ui_inst.CHECKhtfl.setChecked(rqt_data.ht)
                
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
                    rqt=rqt_data
                )
                ui_inst.thread = ExecutionOutputThread(self.ide.root.execution_stub, req_obj)
                ui_inst.thread.output_received.connect(lambda text, u=ui_inst: self.append_to_terminal(u, text))
                ui_inst.thread.session_finished.connect(lambda u=ui_inst: self.on_session_finished(u))
                ui_inst.thread.start()
                
            if active_rqt:
                has_plus = False
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.tabText(i) == "+":
                        has_plus = True
                        break
                if not has_plus:
                    plus_tab = QWidget()
                    self.tab_widget.addTab(plus_tab, "+")
        except Exception as e:
            print(f"Error restoring active rqt sessions: {e}")
