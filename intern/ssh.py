import os, subprocess, re
from PySide6.QtCore import QObject, QSize, QThread, Signal, Qt
from PySide6.QtWidgets import QWidget, QGridLayout, QHBoxLayout, QFrame, QVBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QSpacerItem, QSizePolicy
from PySide6.QtGui import QIcon
from external.rqtll_widgets.forms.g4_ui_ssh import Ui_Widget as Ui_G4

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


class SshController(QObject):
    def __init__(self, ide_controller):
        super().__init__()
        self.ide = ide_controller
        self.tabs = []
        self.is_gz_sim = False

    def bind(self, window):
        self.window = window
        self.ui = window.ui
        self.tab_widget = self.ui.tabWidget
        
        # Setup spacer widget for first tab
        self.ui.spacer_widget = QWidget(self.tab_widget.widget(0))
        spacer_layout = QHBoxLayout(self.ui.spacer_widget)
        spacer_layout.setContentsMargins(0, 0, 0, 0)
        spacer_layout.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.ui.gridLayout.addWidget(self.ui.spacer_widget, 0, 1, 1, 1)
        
        # Apply clean monospace font to terminal
        self.setup_terminal_font(self.ui.textEdit)
        self.show_text_edit(self.ui, False)
        
        self.ui.is_connected = False
        self.ui.tab_page = self.tab_widget.widget(0)
        self.ui.session_id = f"{self.ide.ws_path}_ssh_0"
        self.ui.terminal = VirtualTerminal(rows=36, cols=120)
        self.ui.textEdit.keyPressEvent = lambda event: self.handle_keypress(event, self.ui)
        self.tabs.append(self.ui)
        
        self.ui.BTNConnect.clicked.connect(lambda: self.on_connect_clicked(self.ui))
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

        # Restore active sessions from backend
        self.restore_active_sessions()

    def setup_terminal_font(self, text_edit):
        font = text_edit.font()
        font.setFamily("UbuntuMono Nerd Font Mono")
        font.setStyleHint(font.StyleHint.Monospace)
        text_edit.setFont(font)

    def restore_active_sessions(self):
        try:
            req = types_pb2.Empty()
            res = self.ide.root.execution_stub.GetActiveSessions(req)
            active_ssh = [s for s in res.sessions if s.HasField("ssh")]
            
            for session in active_ssh:
                parts = session.session_id.split('_')
                try:
                    idx = int(parts[-1])
                except ValueError:
                    continue
                
                while self.tab_widget.count() <= idx:
                    new_tab = QWidget()
                    self.tab_widget.addTab(new_tab, f"Conexión {self.tab_widget.count() + 1}")
                
                if idx > 0:
                    self.initialize_tab_ui(idx)
                
                ui_inst = self.tabs[idx]
                ui_inst.session_id = session.session_id
                
                ssh_data = session.ssh
                ui_inst.EDITServer.setText(ssh_data.server)
                ui_inst.EDITUser.setText(ssh_data.username)
                ui_inst.EDITPort.setText(str(ssh_data.port))
                ui_inst.EDITKey.setText(ssh_data.key_path)
                ui_inst.CHECKVerbose.setChecked(ssh_data.verbose)
                
                proto_idx = 0
                if ssh_data.ipv4_only:
                    proto_idx = 1
                elif ssh_data.ipv6_only:
                    proto_idx = 2
                ui_inst.COMBOProtocol.setCurrentIndex(proto_idx)
                
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
                    ssh=ssh_data
                )
                ui_inst.thread = ExecutionOutputThread(self.ide.root.execution_stub, req_obj)
                ui_inst.thread.output_received.connect(lambda text, u=ui_inst: self.append_to_terminal(u, text))
                ui_inst.thread.session_finished.connect(lambda u=ui_inst: self.on_session_finished(u))
                ui_inst.thread.start()

            if active_ssh:
                has_plus = False
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.tabText(i) == "+":
                        has_plus = True
                        break
                if not has_plus:
                    plus_tab = QWidget()
                    self.tab_widget.addTab(plus_tab, "+")
        except Exception as e:
            print(f"Error restoring active sessions: {e}")

    def show_text_edit(self, ui_inst, show):
        if show:
            ui_inst.spacer_widget.hide()
            ui_inst.textEdit.show()
        else:
            ui_inst.textEdit.hide()
            ui_inst.spacer_widget.show()

    def get_display_name(self, ui_inst, idx):
        return ui_inst.EDITServer.text().strip() or f"Conexión {idx}"

    def on_connect_clicked(self, ui_inst):
        tab_idx = self.tab_widget.indexOf(ui_inst.tab_page)
        if tab_idx == -1:
            return

        connected = ui_inst.is_connected
        
        if not connected:
            try:
                ssh_req = interactive_execution_pb2.SshRequest(
                    server=ui_inst.EDITServer.text().strip(),
                    username=ui_inst.EDITUser.text().strip(),
                    port=int(ui_inst.EDITPort.text().strip() or 22),
                    key_path=ui_inst.EDITKey.text().strip(),
                    verbose=ui_inst.CHECKVerbose.isChecked(),
                    ipv4_only=(ui_inst.COMBOProtocol.currentIndex() == 1),
                    ipv6_only=(ui_inst.COMBOProtocol.currentIndex() == 2),
                    password=""
                )
                
                req_obj = interactive_execution_pb2.ExecutionRequest(
                    session_id=ui_inst.session_id,
                    ssh=ssh_req
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
                        'Error de conexión SSH',
                        f'No se pudo iniciar la sesión SSH: {e}']
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
                
            self.tab_widget.setTabText(tab_idx, "+")

    def append_to_terminal(self, ui_inst, text):
        ui_inst.terminal.write(text)
        ui_inst.textEdit.setPlainText(ui_inst.terminal.get_text())
        scrollbar = ui_inst.textEdit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_session_finished(self, ui_inst):
        if ui_inst.is_connected:
            cmd = ['notify-send', '--app-name', 'RQTLL IDE', '--print-id',
                    '--icon', "edit-delete",
                    'SSH Detenido',
                    f'La sesión {self.get_display_name(ui_inst, 1)} se ha desconectado.']
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
                self.tab_widget.setTabText(index, f"Conexión {index + 1}")
                self.initialize_tab_ui(index)

    def initialize_tab_ui(self, index):
        tab_widget = self.tab_widget.widget(index)
        if tab_widget.layout() is not None:
            return
            
        dummy = QWidget()
        ui_inst = Ui_G4()
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
        ui_inst.session_id = f"{self.ide.ws_path}_ssh_{index}"
        ui_inst.terminal = VirtualTerminal(rows=36, cols=120)
        ui_inst.textEdit.keyPressEvent = lambda event: self.handle_keypress(event, ui_inst)
        self.tabs.append(ui_inst)
        
        ui_inst.BTNConnect.clicked.connect(lambda: self.on_connect_clicked(ui_inst))
