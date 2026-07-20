import os, subprocess, re
from PySide6.QtCore import QObject, QSize, QThread, Signal, Qt, QTimer
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QFrame, QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QSpacerItem, QSizePolicy, QFileDialog
from PySide6.QtGui import QIcon, QTextCursor
from external.rqtll_widgets.forms.g6_ui_gz_sim import Ui_Widget as Ui_G6

import types_pb2
import interactive_execution_pb2
import interactive_execution_pb2_grpc

try:
    from external.rqtll_widgets.utils.icon_loader import _resolve_icon
except Exception:
    from rqtll_widgets.utils.icon_loader import _resolve_icon


class VirtualTerminal:
    LINE_DRAWING_MAP = {
        'q': '─',
        'x': '│',
        'l': '┌',
        'k': '┐',
        'm': '└',
        'j': '┘',
        't': '├',
        'u': '┤',
        'v': '┴',
        'w': '┬',
        'n': '┼',
        'a': '▒',
        '~': '·',
    }

    def __init__(self, rows=24, cols=80):
        self.rows = rows
        self.cols = cols
        self.clear()

    def clear(self):
        self.screen = [[' ' for _ in range(self.cols)] for _ in range(self.rows)]
        self.cursor_row = 0
        self.cursor_col = 0
        self.alt_charset = False

    def write(self, text):
        ansi_re = re.compile(r'\x1b\[([?0-9;]*)([a-zA-Z])|\x1b\((.)|\x1b\]([^\x07\x1b]*)(?:\x07|\x1b\\)|\x1b(.)')
        pos = 0
        while pos < len(text):
            match = ansi_re.search(text, pos)
            if not match:
                self.print_string(text[pos:])
                break
            
            if match.start() > pos:
                self.print_string(text[pos:match.start()])
            
            if match.group(2): # CSI sequence
                params = match.group(1)
                cmd = match.group(2)
                self.handle_csi(params, cmd)
            elif match.group(3): # Character set selection ESC ( <char>
                charset = match.group(3)
                if charset == '0':
                    self.alt_charset = True
                elif charset == 'B':
                    self.alt_charset = False
            
            pos = match.end()

    def print_string(self, s):
        for char in s:
            if char == '\x0e': # SO (Shift Out) -> Select Alt Charset
                self.alt_charset = True
                continue
            elif char == '\x0f': # SI (Shift In) -> Select Normal Charset
                self.alt_charset = False
                continue

            if char == '\n':
                self.cursor_row += 1
                self.cursor_col = 0
                if self.cursor_row >= self.rows:
                    self.scroll_up()
            elif char == '\r':
                self.cursor_col = 0
            elif char == '\t':
                self.cursor_col = (self.cursor_col + 8) & ~7
                if self.cursor_col >= self.cols:
                    self.cursor_col = self.cols - 1
            elif char == '\x08' or char == '\x7f':
                if self.cursor_col > 0:
                    self.cursor_col -= 1
            else:
                if self.alt_charset:
                    char = self.LINE_DRAWING_MAP.get(char, char)

                if self.cursor_row >= self.rows:
                    self.scroll_up()
                if self.cursor_col >= self.cols:
                    self.cursor_row += 1
                    self.cursor_col = 0
                    if self.cursor_row >= self.rows:
                        self.scroll_up()
                
                self.screen[self.cursor_row][self.cursor_col] = char
                self.cursor_col += 1

    def scroll_up(self):
        self.screen.pop(0)
        self.screen.append([' ' for _ in range(self.cols)])
        self.cursor_row = self.rows - 1

    def handle_csi(self, params, cmd):
        parts = [int(p) for p in params.split(';') if p.isdigit()]
        
        if cmd == 'A':
            n = parts[0] if parts else 1
            self.cursor_row = max(0, self.cursor_row - n)
        elif cmd == 'B':
            n = parts[0] if parts else 1
            self.cursor_row = min(self.rows - 1, self.cursor_row + n)
        elif cmd == 'C':
            n = parts[0] if parts else 1
            self.cursor_col = min(self.cols - 1, self.cursor_col + n)
        elif cmd == 'D':
            n = parts[0] if parts else 1
            self.cursor_col = max(0, self.cursor_col - n)
        elif cmd == 'H' or cmd == 'f':
            r = parts[0] - 1 if len(parts) > 0 else 0
            c = parts[1] - 1 if len(parts) > 1 else 0
            self.cursor_row = max(0, min(self.rows - 1, r))
            self.cursor_col = max(0, min(self.cols - 1, c))
        elif cmd == 'J':
            mode = parts[0] if parts else 0
            if mode == 2:
                self.clear()
        elif cmd == 'K':
            mode = parts[0] if parts else 0
            if mode == 0:
                for c in range(self.cursor_col, self.cols):
                    self.screen[self.cursor_row][c] = ' '
            elif mode == 1:
                for c in range(0, self.cursor_col + 1):
                    self.screen[self.cursor_row][c] = ' '
            elif mode == 2:
                self.screen[self.cursor_row] = [' ' for _ in range(self.cols)]
        elif cmd == 'm':
            pass

    def get_text(self):
        lines = []
        for line in self.screen:
            lines.append("".join(line).rstrip())
        while len(lines) > 1 and not lines[-1]:
            lines.pop()
        return "\n".join(lines)


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


class GzLauncherController(QObject):
    def __init__(self, ide_controller):
        super().__init__()
        self.ide = ide_controller
        self.tabs = []
        self.is_gz_sim = True

    def bind(self, window):
        self.window = window
        self.ui = window.ui
        self.tab_widget = self.ui.tabWidget
        
        # Create spacer widget for the first tab
        self.ui.spacer_widget = QWidget(self.tab_widget.widget(0))
        spacer_layout = QHBoxLayout(self.ui.spacer_widget)
        spacer_layout.setContentsMargins(0, 0, 0, 0)
        spacer_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.ui.gridLayout.addWidget(self.ui.spacer_widget, 1, 2, 1, 1)
        
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
        self.ui.session_id = f"{self.ide.ws_path}_gz_sim_0"
        self.ui.terminal = VirtualTerminal(rows=1000, cols=100)
        self.ui.textEdit.keyPressEvent = lambda event: self.handle_keypress(event, self.ui)
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

    def show_text_edit(self, ui_inst, show):
        if show:
            ui_inst.spacer_widget.hide()
            ui_inst.textEdit.show()
        else:
            ui_inst.textEdit.hide()
            ui_inst.spacer_widget.show()

    def get_display_name(self, ui_inst, idx):
        try:
            sdf_path = ui_inst.EDITSdf.text().strip()
            return os.path.basename(sdf_path) if sdf_path else f"Simulación {idx}"
        except Exception:
            return f"Simulación {idx}"

    def clear_combobox_selections(self, ui_inst):
        combos = [
            ui_inst.COMBORunMode,
            ui_inst.COMBOPysicsEngine,
            ui_inst.COMBORenderEngine,
            ui_inst.COMBOGUIEngine,
            ui_inst.COMBOServerEngine,
            ui_inst.COMBOAPI,
            ui_inst.COMBOAPIGUI,
            ui_inst.COMBOAPIServer,
            ui_inst.COMBOSecondary,
            ui_inst.COMBORecordTopics
        ]
        for combo in combos:
            combo.setCurrentIndex(-1)

    def setup_ui_interactions(self, ui_inst):
        # RADIO buttons toggled logic to hide/show toolbox vs playback horizontal layout
        def on_radio_toggled(ui):
            is_run = ui.RADIOSIMRun.isChecked()
            ui.toolBox.setVisible(is_run)
            ui.label_11.setVisible(not is_run)
            ui.EDITSIMPlay.setVisible(not is_run)
            ui.BTNSIMPlay.setVisible(not is_run)

        ui_inst.RADIOSIMRun.toggled.connect(lambda: on_radio_toggled(ui_inst))
        ui_inst.RADIOSIMPlay.toggled.connect(lambda: on_radio_toggled(ui_inst))
        on_radio_toggled(ui_inst)

        # File and Directory selection dialogs
        def select_sdf(ui):
            path, _ = QFileDialog.getOpenFileName(self.window, "Seleccionar archivo SDF", self.ide.ws_path, "Archivos SDF/World (*.sdf *.world);;Todos los archivos (*)")
            if path:
                ui.EDITSdf.setText(path)

        def select_config(ui):
            path, _ = QFileDialog.getOpenFileName(self.window, "Seleccionar archivo de configuración GUI", self.ide.ws_path, "Archivos Config (*.config);;Todos los archivos (*)")
            if path:
                ui.EDITConfig.setText(path)

        def select_record_dir(ui):
            path = QFileDialog.getExistingDirectory(self.window, "Seleccionar directorio de grabación", self.ide.ws_path)
            if path:
                ui.EDITRecordDir.setText(path)

        def select_play_dir(ui):
            path = QFileDialog.getExistingDirectory(self.window, "Seleccionar directorio de simulación a reproducir", self.ide.ws_path)
            if path:
                ui.EDITSIMPlay.setText(path)

        ui_inst.BTNSdf.clicked.connect(lambda: select_sdf(ui_inst))
        ui_inst.BTNConfig.clicked.connect(lambda: select_config(ui_inst))
        ui_inst.BTNRecordDir.clicked.connect(lambda: select_record_dir(ui_inst))
        ui_inst.BTNSIMPlay.clicked.connect(lambda: select_play_dir(ui_inst))

        # Render engine combobox dependencies
        def handle_render_engine_changed(ui):
            idx = ui.COMBORenderEngine.currentIndex()
            if idx >= 0:
                ui.COMBOGUIEngine.blockSignals(True)
                ui.COMBOServerEngine.blockSignals(True)
                ui.COMBOGUIEngine.setCurrentIndex(idx)
                ui.COMBOServerEngine.setCurrentIndex(idx)
                ui.COMBOGUIEngine.blockSignals(False)
                ui.COMBOServerEngine.blockSignals(False)

        def handle_gui_or_server_engine_changed(ui):
            ui.COMBORenderEngine.blockSignals(True)
            ui.COMBORenderEngine.setCurrentIndex(-1)
            ui.COMBORenderEngine.blockSignals(False)

        ui_inst.COMBORenderEngine.currentIndexChanged.connect(lambda: handle_render_engine_changed(ui_inst))
        ui_inst.COMBOGUIEngine.currentIndexChanged.connect(lambda: handle_gui_or_server_engine_changed(ui_inst))
        ui_inst.COMBOServerEngine.currentIndexChanged.connect(lambda: handle_gui_or_server_engine_changed(ui_inst))

        # API combobox dependencies
        def handle_api_changed(ui):
            idx = ui.COMBOAPI.currentIndex()
            if idx >= 0:
                ui.COMBOAPIGUI.blockSignals(True)
                ui.COMBOAPIServer.blockSignals(True)
                ui.COMBOAPIGUI.setCurrentIndex(idx)
                ui.COMBOAPIServer.setCurrentIndex(idx)
                ui.COMBOAPIGUI.blockSignals(False)
                ui.COMBOAPIServer.blockSignals(False)

        def handle_gui_or_server_api_changed(ui):
            ui.COMBOAPI.blockSignals(True)
            ui.COMBOAPI.setCurrentIndex(-1)
            ui.COMBOAPI.blockSignals(False)

        ui_inst.COMBOAPI.currentIndexChanged.connect(lambda: handle_api_changed(ui_inst))
        ui_inst.COMBOAPIGUI.currentIndexChanged.connect(lambda: handle_gui_or_server_api_changed(ui_inst))
        ui_inst.COMBOAPIServer.currentIndexChanged.connect(lambda: handle_gui_or_server_api_changed(ui_inst))

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
                
                # sdf file
                if ui_inst.RADIOSIMRun.isChecked():
                    val = ui_inst.EDITSdf.text().strip()
                    if val:
                        kwargs["sdf_file"] = val
                        
                # gui config
                val = ui_inst.EDITConfig.text().strip()
                if val:
                    kwargs["gui_config"] = val
                    
                # run mode
                run_mode = ui_inst.COMBORunMode.currentIndex()
                if run_mode == 1:
                    kwargs["server_only"] = True
                elif run_mode == 2:
                    kwargs["gui_only"] = True
                    
                # update rate
                val = ui_inst.SPINHzRate.value()
                if val > 0.0:
                    kwargs["update_rate"] = val
                    
                # seed
                if ui_inst.CHECKhtfl_2.isChecked():
                    val = ui_inst.SPINSeed.value()
                    if val != 0:
                        kwargs["seed"] = val
                        
                # wait for assets
                if ui_inst.RADIOWaitAssets.isChecked():
                    kwargs["wait_for_assets"] = True
                    
                # run on start
                if ui_inst.RADIORunAtStart.isChecked():
                    kwargs["run_on_start"] = True
                    
                # physics engine
                if ui_inst.COMBOPysicsEngine.currentIndex() >= 0:
                    val = ui_inst.COMBOPysicsEngine.currentText().strip()
                    if val:
                        kwargs["physics_engine"] = val
                        
                # render engines
                if ui_inst.COMBORenderEngine.currentIndex() >= 0:
                    val = ui_inst.COMBORenderEngine.currentText().strip()
                    if val:
                        kwargs["render_engine"] = val
                if ui_inst.COMBOGUIEngine.currentIndex() >= 0:
                    val = ui_inst.COMBOGUIEngine.currentText().strip()
                    if val:
                        kwargs["render_engine_gui"] = val
                if ui_inst.COMBOServerEngine.currentIndex() >= 0:
                    val = ui_inst.COMBOServerEngine.currentText().strip()
                    if val:
                        kwargs["render_engine_server"] = val
                        
                # APIs
                def get_api_val(combo):
                    if combo.currentIndex() < 0:
                        return ""
                    txt = combo.currentText().strip()
                    return txt.split()[0].lower() if txt else ""
                    
                val = get_api_val(ui_inst.COMBOAPI)
                if val:
                    kwargs["render_engine_api_backend"] = val
                val = get_api_val(ui_inst.COMBOAPIGUI)
                if val:
                    kwargs["render_engine_gui_api_backend"] = val
                val = get_api_val(ui_inst.COMBOAPIServer)
                if val:
                    kwargs["render_engine_server_api_backend"] = val
                    
                # network
                val = ui_inst.SPINSecondaries.value()
                if val > 0:
                    kwargs["network_secondaries"] = val
                if ui_inst.COMBOSecondary.currentIndex() >= 0:
                    kwargs["network_role"] = "primary" if ui_inst.COMBOSecondary.currentIndex() == 0 else "secondary"
                    
                # record
                if ui_inst.CHECKRecord.isChecked():
                    val = ui_inst.EDITSdf.text().strip() if ui_inst.RADIOSIMRun.isChecked() else ui_inst.EDITSIMPlay.text().strip()
                    if val:
                        kwargs["record"] = val
                    val = ui_inst.EDITRecordDir.text().strip()
                    if val:
                        kwargs["record_path"] = val
                    if ui_inst.CHECKRecordMaterials.isChecked():
                        kwargs["record_resources"] = True
                    if ui_inst.COMBORecordTopics.currentIndex() == 1:
                        kwargs["record_topics"] = ["*"]
                    val = ui_inst.SPINRecordPeriod.value()
                    if val > 0.0:
                        kwargs["record_period"] = val
                    if ui_inst.CHECKRecordOverwrite.isChecked():
                        kwargs["log_overwrite"] = True
                    if ui_inst.CHECKRecordZip.isChecked():
                        kwargs["log_compress"] = True
                        
                # playback
                if ui_inst.RADIOSIMPlay.isChecked():
                    val = ui_inst.EDITSIMPlay.text().strip()
                    if val:
                        kwargs["playback"] = val

                gz_req = interactive_execution_pb2.GzSimRequest(**kwargs)
                
                req_obj = interactive_execution_pb2.ExecutionRequest(
                    session_id=ui_inst.session_id,
                    gz_sim=gz_req
                )
                
                ui_inst.terminal.clear()
                ui_inst.textEdit.clear()
                
                ui_inst.thread = ExecutionOutputThread(self.ide.root.execution_stub, req_obj)
                ui_inst.thread.output_received.connect(lambda text, u=ui_inst: self.append_to_terminal(u, text))
                ui_inst.thread.session_finished.connect(lambda u=ui_inst: self.on_session_finished(u))
                ui_inst.thread.start()
            except Exception as e:
                cmd = ['notify-send', '--app-name', 'RQTLL IDE', '--print-id',
                        '--icon', "edit-delete",
                        'Error de simulación Gazebo',
                        f'No se pudo iniciar la simulación: {e}']
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
        ui_inst.terminal.write(text)
        if not getattr(ui_inst, "pending_update", False):
            ui_inst.pending_update = True
            ui_inst.refresh_timer.start(30)

    def refresh_terminal_view(self, ui_inst):
        ui_inst.pending_update = False
        ui_inst.textEdit.setPlainText(ui_inst.terminal.get_text())
        
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
                    'Simulación Detenida',
                    f'La simulación {self.get_display_name(ui_inst, 1)} se ha desconectado.']
            if self.ide.root.current_notify_id:
                cmd.extend(['--replace-id', self.ide.root.current_notify_id.strip()])
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
            self.ide.root.current_notify_id, _ = process.communicate()
            self.on_connect_clicked(ui_inst)

    def handle_keypress(self, event, ui_inst):
        text = event.text()
        if not text:
            key = event.key()
            if key == Qt.Key_Return or key == Qt.Key_Enter:
                text = "\r"
            elif key == Qt.Key_Backspace:
                text = "\x7f"
            elif key == Qt.Key_Tab:
                text = "\t"
            elif key == Qt.Key_Escape:
                text = "\x1b"
            elif key == Qt.Key_Up:
                text = "\x1b[A"
            elif key == Qt.Key_Down:
                text = "\x1b[B"
            elif key == Qt.Key_Right:
                text = "\x1b[C"
            elif key == Qt.Key_Left:
                text = "\x1b[D"
            elif key == Qt.Key_Delete:
                text = "\x1b[3~"
            else:
                return

        try:
            req = interactive_execution_pb2.ExecutionInput(
                session_id=ui_inst.session_id,
                data=text.encode('utf-8')
            )
            self.ide.root.execution_stub.SendInput(req)
        except Exception as e:
            print(f"Error sending input: {e}")

    def on_tab_changed(self, index):
        if index >= 0 and index < self.tab_widget.count():
            if self.tab_widget.tabText(index) == "+" and self.tab_widget.widget(index).layout() is None:
                self.tab_widget.setTabText(index, f"Simulación {index + 1}")
                self.initialize_tab_ui(index)

    def initialize_tab_ui(self, index):
        tab_widget = self.tab_widget.widget(index)
        if tab_widget.layout() is not None:
            return
            
        dummy = QWidget()
        ui_inst = Ui_G6()
        ui_inst.setupUi(dummy, icon_dirs=self.window._initial_icon_dirs, theme=self.window._initial_theme)
        
        grid_layout = QGridLayout(tab_widget)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.addWidget(ui_inst.frame_2, 1, 1, 1, 1)
        grid_layout.addWidget(ui_inst.textEdit, 1, 2, 1, 1)
        
        ui_inst.spacer_widget = QWidget(tab_widget)
        spacer_layout = QHBoxLayout(ui_inst.spacer_widget)
        spacer_layout.setContentsMargins(0, 0, 0, 0)
        spacer_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        grid_layout.addWidget(ui_inst.spacer_widget, 1, 2, 1, 1)
        
        self.setup_terminal_font(ui_inst.textEdit)
        self.show_text_edit(ui_inst, False)
        
        ui_inst.is_connected = False
        ui_inst.tab_page = tab_widget
        ui_inst.session_id = f"{self.ide.ws_path}_gz_sim_{index}"
        ui_inst.terminal = VirtualTerminal(rows=1000, cols=100)
        ui_inst.textEdit.keyPressEvent = lambda event: self.handle_keypress(event, ui_inst)
        
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
            active_gz = [s for s in res.sessions if s.HasField("gz_sim")]
            
            for session in active_gz:
                parts = session.session_id.split('_')
                try:
                    idx = int(parts[-1])
                except ValueError:
                    continue
                
                while self.tab_widget.count() <= idx:
                    new_tab = QWidget()
                    self.tab_widget.addTab(new_tab, f"Simulación {self.tab_widget.count() + 1}")
                
                while len(self.tabs) <= idx:
                    self.tabs.append(None)
                if self.tabs[idx] is None:
                    self.initialize_tab_ui(idx)
                
                ui_inst = self.tabs[idx]
                ui_inst.session_id = session.session_id
                
                gz_data = session.gz_sim
                ui_inst.EDITSdf.setText(gz_data.sdf_file)
                ui_inst.EDITConfig.setText(gz_data.gui_config)
                
                mode_idx = 0
                if gz_data.server_only:
                    mode_idx = 1
                elif gz_data.gui_only:
                    mode_idx = 2
                ui_inst.COMBORunMode.setCurrentIndex(mode_idx)
                
                ui_inst.SPINHzRate.setValue(gz_data.update_rate)
                
                if gz_data.seed != 0:
                    ui_inst.CHECKhtfl_2.setChecked(True)
                    ui_inst.SPINSeed.setValue(gz_data.seed)
                else:
                    ui_inst.CHECKhtfl_2.setChecked(False)
                    
                ui_inst.RADIOWaitAssets.setChecked(gz_data.wait_for_assets)
                ui_inst.RADIORunAtStart.setChecked(gz_data.run_on_start)
                
                if gz_data.record or gz_data.record_path:
                    ui_inst.CHECKRecord.setChecked(True)
                    ui_inst.EDITRecordDir.setText(gz_data.record_path)
                    ui_inst.CHECKRecordMaterials.setChecked(gz_data.record_resources)
                    if "*" in gz_data.record_topics:
                        ui_inst.COMBORecordTopics.setCurrentIndex(1)
                    else:
                        ui_inst.COMBORecordTopics.setCurrentIndex(0)
                    ui_inst.SPINRecordPeriod.setValue(gz_data.record_period)
                    ui_inst.CHECKRecordOverwrite.setChecked(gz_data.log_overwrite)
                    ui_inst.CHECKRecordZip.setChecked(gz_data.log_compress)
                else:
                    ui_inst.CHECKRecord.setChecked(False)
                    
                if gz_data.playback:
                    ui_inst.RADIOSIMPlay.setChecked(True)
                    ui_inst.EDITSIMPlay.setText(gz_data.playback)
                else:
                    ui_inst.RADIOSIMRun.setChecked(True)

                def select_combo_text(combo, text):
                    if not text:
                        combo.setCurrentIndex(-1)
                        return
                    for i in range(combo.count()):
                        if combo.itemText(i).strip() == text.strip():
                            combo.setCurrentIndex(i)
                            return
                    combo.setCurrentIndex(-1)
                            
                select_combo_text(ui_inst.COMBOPysicsEngine, gz_data.physics_engine)
                select_combo_text(ui_inst.COMBORenderEngine, gz_data.render_engine)
                select_combo_text(ui_inst.COMBOGUIEngine, gz_data.render_engine_gui)
                select_combo_text(ui_inst.COMBOServerEngine, gz_data.render_engine_server)
                
                def select_combo_api(combo, api_val):
                    if not api_val:
                        combo.setCurrentIndex(-1)
                        return
                    for i in range(combo.count()):
                        if combo.itemText(i).split()[0].lower() == api_val.lower():
                            combo.setCurrentIndex(i)
                            return
                    combo.setCurrentIndex(-1)
                            
                select_combo_api(ui_inst.COMBOAPI, gz_data.render_engine_api_backend)
                select_combo_api(ui_inst.COMBOAPIGUI, gz_data.render_engine_gui_api_backend)
                select_combo_api(ui_inst.COMBOAPIServer, gz_data.render_engine_server_api_backend)
                
                ui_inst.SPINSecondaries.setValue(gz_data.network_secondaries)
                ui_inst.COMBOSecondary.setCurrentIndex(0 if gz_data.network_role == "primary" else 1)
                
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
                    gz_sim=gz_data
                )
                ui_inst.thread = ExecutionOutputThread(self.ide.root.execution_stub, req_obj)
                ui_inst.thread.output_received.connect(lambda text, u=ui_inst: self.append_to_terminal(u, text))
                ui_inst.thread.session_finished.connect(lambda u=ui_inst: self.on_session_finished(u))
                ui_inst.thread.start()
                
            if active_gz:
                has_plus = False
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.tabText(i) == "+":
                        has_plus = True
                        break
                if not has_plus:
                    plus_tab = QWidget()
                    self.tab_widget.addTab(plus_tab, "+")
        except Exception as e:
            print(f"Error restoring active gz sessions: {e}")
