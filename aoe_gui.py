"""
Chương trình: aoe_gui.py
Giao diện PyQt6 hỗ trợ nhóm chơi Age of Empires 1 (Đế Chế) qua ZeroTier.
Các tính năng:
- Chế độ Host (Mở phòng TCP, tự động phát hiện IP ZeroTier, xem danh sách người chơi, kick người chơi).
- Chế độ Client (Kiểm tra kết nối TCP tới Host, báo trạng thái OK/Lỗi, đo độ trễ Ping thời gian thực).
- Phòng Chat nhóm chung giữa Host và các Client.
- Giao diện Dark Gaming hiện đại, mượt mà, tối ưu trên Windows.
"""

import os
import sys
import subprocess

# Tự động chuyển sang môi trường ảo .venv nếu đang chạy bằng Python hệ thống
def _ensure_venv():
    in_venv = (sys.prefix != getattr(sys, "base_prefix", sys.prefix))
    if not in_venv:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        venv_python = os.path.join(current_dir, ".venv", "Scripts", "python.exe")
        if os.path.exists(venv_python) and os.path.abspath(sys.executable).lower() != os.path.abspath(venv_python).lower():
            try:
                res = subprocess.run([venv_python] + sys.argv)
                sys.exit(res.returncode)
            except Exception:
                pass

_ensure_venv()
import tel
import time
import json
import socket
import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QTimer
from PyQt6.QtGui import QFont, QIcon, QTextCursor, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QTabWidget, QGroupBox,
    QMessageBox, QFrame, QSplitter, QCheckBox, QComboBox, QFileDialog
)

# Cổng mặc định theo chuẩn DirectPlay của AoE 1
DEFAULT_PORT = 2300
BUFFER_SIZE = 4096


def get_current_time():
    """Lấy thời gian dạng Giờ:Phút:Giây."""
    return datetime.now().strftime("%H:%M:%S")


def get_all_ip_addresses():
    """Lấy danh sách tất cả các địa chỉ IPv4 của máy hiện tại để tìm IP ZeroTier."""
    ip_list = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                ip_list.append(ip)
    except Exception:
        pass

    if not ip_list:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip_list.append(s.getsockname()[0])
            s.close()
        except Exception:
            ip_list.append("127.0.0.1")

    return list(dict.fromkeys(ip_list))


try:
    import winsound
except ImportError:
    winsound = None


def play_sound_alert(sound_type="ready", base_dir=""):
    """Phát âm thanh báo hiệu khi có người Ready hoặc khi Host Bắt đầu."""
    try:
        if winsound:
            sound_file = ""
            if sound_type == "ready":
                sound_file = os.path.join(base_dir, "game-de-che-1", "sound", "Taunt001.wav")
            elif sound_type == "start":
                sound_file = os.path.join(base_dir, "game-de-che-1", "sound", "Taunt016.wav")

            if sound_file and os.path.exists(sound_file):
                winsound.PlaySound(sound_file, winsound.SND_FILENAME | winsound.SND_ASYNC)
            else:
                winsound.MessageBeep(winsound.MB_ICONASTERISK if sound_type == "ready" else winsound.MB_ICONEXCLAMATION)
    except Exception:
        pass


def set_directplay_registry_ip(ip_address):
    """Ghi sẵn địa chỉ IP của Host vào Registry DirectPlay của Windows để khi mở game không cần gõ."""
    try:
        import winreg
        keys = [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Microsoft Games\Age of Empires\1.0\Multiplayer"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Microsoft Games\Age of Empires Expansion\1.0\Multiplayer"),
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\DirectPlay\Service Providers\Internet TCP/IP Connection For DirectPlay"),
        ]
        for root, subkey in keys:
            try:
                with winreg.CreateKey(root, subkey) as key:
                    winreg.SetValueEx(key, "Address", 0, winreg.REG_SZ, str(ip_address))
                    winreg.SetValueEx(key, "LastIP", 0, winreg.REG_SZ, str(ip_address))
            except Exception:
                pass
    except Exception:
        pass


# ==============================================================================
# BỘ TÍN HIỆU ĐIỀU PHỐI (SIGNALS) ĐỂ CẬP NHẬT GIAO DIỆN AN TOÀN
# ==============================================================================
class NetworkSignals(QObject):
    # Tín hiệu cho Host
    client_connected = pyqtSignal(str, str, str)  # name, ip_port, time
    client_disconnected = pyqtSignal(str, str)    # name, ip
    client_ready_changed = pyqtSignal(str, bool)  # name, is_ready
    
    # Tín hiệu chung (Chat & Trạng thái)
    new_chat_message = pyqtSignal(str, str, str)  # sender, message, time
    system_log = pyqtSignal(str, str)              # message, level (info, success, warning, error)
    
    # Tín hiệu cho Client
    client_status_changed = pyqtSignal(bool, str) # is_connected, status_message
    ping_result = pyqtSignal(float)               # latency_ms
    game_started_by_host = pyqtSignal(str)        # host_ip
    room_discovered = pyqtSignal(str, str, int, int) # host_name, host_ip, port, count


# ==============================================================================
# BACKEND NETWORK CHO MÁY CHỦ (HOST)
# ==============================================================================
class HostEngine:
    def __init__(self, port, host_name, signals):
        self.port = port
        self.host_name = host_name
        self.signals = signals
        self.server_socket = None
        self.running = False
        # Lưu các client: {socket: {"name": str, "addr": tuple, "join_time": str}}
        self.clients = {}
        self.lock = threading.Lock()

    def start(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("0.0.0.0", self.port))
            self.server_socket.listen(10)
            self.running = True

            self.signals.system_log.emit(
                f"Máy chủ đã mở thành công trên cổng TCP {self.port}!", "success"
            )

            threading.Thread(target=self._accept_loop, daemon=True).start()
            threading.Thread(target=self._discovery_broadcast_loop, daemon=True).start()
            return True, "Khởi động thành công"
        except Exception as e:
            self.signals.system_log.emit(f"Không thể mở cổng {self.port}: {e}", "error")
            return False, str(e)

    def _discovery_broadcast_loop(self):
        """Phát tín hiệu UDP định kỳ để các máy Client tự động tìm thấy phòng qua ZeroTier."""
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_sock.settimeout(1.0)

        host_ips = get_all_ip_addresses()
        primary_ip = host_ips[0] if host_ips else "127.0.0.1"
        for ip in host_ips:
            if ip.startswith(("10.", "172.", "192.168.19")):
                primary_ip = ip
                break

        while self.running:
            try:
                with self.lock:
                    count = len(self.clients) + 1
                
                payload = json.dumps({
                    "tag": "AOE_BEACON",
                    "host_name": self.host_name,
                    "host_ip": primary_ip,
                    "port": self.port,
                    "player_count": count
                }).encode("utf-8")

                # Gửi broadcast chung và localhost
                udp_sock.sendto(payload, ("255.255.255.255", 2302))
                udp_sock.sendto(payload, ("127.0.0.1", 2302))

                # Gửi tới subnet broadcast của các card mạng (ZeroTier)
                for ip in host_ips:
                    parts = ip.split(".")
                    if len(parts) == 4:
                        subnet_bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                        try:
                            udp_sock.sendto(payload, (subnet_bcast, 2302))
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(1.5)

        try:
            udp_sock.close()
        except Exception:
            pass

    def _accept_loop(self):
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
                threading.Thread(
                    target=self._handle_client, args=(client_sock, addr), daemon=True
                ).start()
            except Exception:
                break

    def _handle_client(self, client_sock, addr):
        buffer = ""
        client_name = f"{addr[0]}:{addr[1]}"
        registered = False

        try:
            while self.running:
                data = client_sock.recv(BUFFER_SIZE)
                if not data:
                    break

                buffer += data.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        packet = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_type = packet.get("type")

                    if msg_type == "join":
                        client_name = packet.get("name", client_name).strip()
                        join_time = get_current_time()
                        ip_port = f"{addr[0]}:{addr[1]}"
                        with self.lock:
                            self.clients[client_sock] = {
                                "name": client_name,
                                "addr": addr,
                                "join_time": join_time,
                                "ready": False
                            }
                        registered = True

                        self.signals.client_connected.emit(client_name, ip_port, join_time)
                        self.signals.system_log.emit(
                            f"Người chơi '{client_name}' ({ip_port}) đã vào phòng.", "info"
                        )

                        # Chào mừng client
                        self._send_packet(client_sock, {
                            "type": "system",
                            "msg": f"Chào mừng {client_name}! Bạn đã kết nối tới Host ({self.host_name})."
                        })

                        # Báo cho các client khác
                        self._broadcast({
                            "type": "system",
                            "msg": f"'{client_name}' ({addr[0]}) đã vào phòng."
                        }, exclude_sock=client_sock)

                    elif msg_type == "ready":
                        is_ready = bool(packet.get("ready", False))
                        with self.lock:
                            if client_sock in self.clients:
                                self.clients[client_sock]["ready"] = is_ready
                        self.signals.client_ready_changed.emit(client_name, is_ready)
                        status_str = "đã SẴN SÀNG! 🟢" if is_ready else "hủy sẵn sàng ⏳"
                        self.signals.system_log.emit(f"'{client_name}' {status_str}", "success" if is_ready else "info")
                        self._broadcast({
                            "type": "chat",
                            "name": "🔔 Hệ Thống",
                            "text": f"Người chơi '{client_name}' {status_str}",
                            "time": get_current_time()
                        })

                    elif msg_type == "chat":
                        sender = packet.get("name", client_name)
                        msg_text = packet.get("text", "")
                        timestamp = get_current_time()
                        self.signals.new_chat_message.emit(sender, msg_text, timestamp)
                        self._broadcast({
                            "type": "chat",
                            "name": sender,
                            "text": msg_text,
                            "time": timestamp
                        }, exclude_sock=client_sock)

                    elif msg_type == "ping":
                        pong_packet = {
                            "type": "pong",
                            "client_time": packet.get("client_time", 0)
                        }
                        self._send_packet(client_sock, pong_packet)

        except (ConnectionResetError, ConnectionAbortedError, socket.error):
            pass
        finally:
            with self.lock:
                info = self.clients.pop(client_sock, None)

            try:
                client_sock.close()
            except Exception:
                pass

            if info and registered:
                name = info["name"]
                ip_str = info["addr"][0]
                self.signals.client_disconnected.emit(name, ip_str)
                self.signals.system_log.emit(f"'{name}' đã rời phòng.", "warning")
                self._broadcast({"type": "system", "msg": f"'{name}' đã rời phòng."})

    def broadcast_start_game(self, host_ip):
        """Gửi lệnh bắt đầu game tới tất cả các client để cùng mở game."""
        self._broadcast({
            "type": "start_game",
            "host_ip": host_ip
        })
        self.signals.system_log.emit("🚀 Đã gửi lệnh BẮT ĐẦU TRẬN ĐẤU tới tất cả người chơi!", "success")

    def _send_packet(self, sock, packet):
        try:
            data = (json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8")
            sock.sendall(data)
        except Exception:
            pass

    def _broadcast(self, packet, exclude_sock=None):
        with self.lock:
            sockets = list(self.clients.keys())
        for sock in sockets:
            if sock != exclude_sock:
                self._send_packet(sock, packet)

    def send_chat(self, text):
        """Host gửi tin nhắn chat."""
        t = get_current_time()
        sender = f"👑 {self.host_name} (Host)"
        self.signals.new_chat_message.emit(sender, text, t)
        self._broadcast({
            "type": "chat",
            "name": sender,
            "text": text,
            "time": t
        })

    def kick_player(self, player_name):
        """Mời một người chơi ra khỏi phòng."""
        target_sock = None
        with self.lock:
            for s, info in self.clients.items():
                if info["name"] == player_name:
                    target_sock = s
                    break

        if target_sock:
            self._send_packet(target_sock, {
                "type": "system",
                "msg": "Bạn đã bị Chủ phòng mời ra khỏi phòng."
            })
            try:
                target_sock.close()
            except Exception:
                pass
            return True
        return False

    def stop(self):
        """Dừng máy chủ Host."""
        self.running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception:
                pass
        with self.lock:
            for sock in self.clients:
                try:
                    sock.close()
                except Exception:
                    pass
            self.clients.clear()
        self.signals.system_log.emit("Máy chủ đã dừng.", "info")


# ==============================================================================
# BACKEND NETWORK CHO MÁY KHÁCH (CLIENT)
# ==============================================================================
class ClientEngine:
    def __init__(self, host_ip, port, player_name, signals):
        self.host_ip = host_ip
        self.port = port
        self.player_name = player_name
        self.signals = signals
        self.sock = None
        self.running = False
        self.ping_event = threading.Event()

    def connect(self):
        start_time = time.time()
        try:
            self.signals.system_log.emit(
                f"Đang kết nối tới Host {self.host_ip}:{self.port} ...", "info"
            )
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(4.0)
            s.connect((self.host_ip, self.port))
            handshake_latency = (time.time() - start_time) * 1000

            self.sock = s
            self.sock.settimeout(None)
            self.running = True

            # Gửi gói tham gia
            self._send_packet({"type": "join", "name": self.player_name})

            self.signals.client_status_changed.emit(
                True, f"ĐÃ KẾT NỐI (Bắt tay: {handshake_latency:.1f} ms)"
            )
            self.signals.system_log.emit(
                f"[OK] Kết nối thành công tới Host ({self.host_ip}:{self.port})!", "success"
            )

            threading.Thread(target=self._recv_loop, daemon=True).start()
            return True, "Thành công"
        except socket.timeout:
            err = "Hết thời gian chờ (Timeout). Kiểm tra lại IP ZeroTier hoặc Tường lửa máy Host."
            self.signals.client_status_changed.emit(False, "LỖI: Timeout kết nối")
            self.signals.system_log.emit(err, "error")
            return False, err
        except ConnectionRefusedError:
            err = "Host từ chối kết nối. Hãy đảm bảo máy Host đã ấn 'Khởi Động Server'."
            self.signals.client_status_changed.emit(False, "LỖI: Host từ chối kết nối")
            self.signals.system_log.emit(err, "error")
            return False, err
        except Exception as e:
            err = f"Lỗi kết nối: {e}"
            self.signals.client_status_changed.emit(False, f"LỖI: {e}")
            self.signals.system_log.emit(err, "error")
            return False, err

    def _recv_loop(self):
        buffer = ""
        while self.running:
            try:
                data = self.sock.recv(BUFFER_SIZE)
                if not data:
                    break

                buffer += data.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        packet = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg_type = packet.get("type")
                    if msg_type == "chat":
                        self.signals.new_chat_message.emit(
                            packet.get("name", "Người lạ"),
                            packet.get("text", ""),
                            packet.get("time", get_current_time())
                        )
                    elif msg_type == "system":
                        self.signals.system_log.emit(packet.get("msg", ""), "info")
                    elif msg_type == "pong":
                        sent_time = packet.get("client_time", 0)
                        latency = (time.time() - sent_time) * 1000
                        self.signals.ping_result.emit(latency)
                        self.ping_event.set()
                    elif msg_type == "start_game":
                        host_ip = packet.get("host_ip", self.host_ip)
                        self.signals.game_started_by_host.emit(host_ip)

            except Exception:
                break

        if self.running:
            self.running = False
            self.signals.client_status_changed.emit(False, "MẤT KẾT NỐI VỚI HOST")
            self.signals.system_log.emit("Đã ngắt kết nối với máy chủ Host.", "warning")

    def _send_packet(self, packet):
        try:
            data = (json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8")
            self.sock.sendall(data)
        except Exception:
            pass

    def send_ready(self, is_ready):
        """Client gửi trạng thái Sẵn Sàng (Ready) tới Host."""
        self._send_packet({"type": "ready", "ready": is_ready})

    def send_chat(self, text):
        t = get_current_time()
        self.signals.new_chat_message.emit(f"Bạn ({self.player_name})", text, t)
        self._send_packet({"type": "chat", "name": self.player_name, "text": text})

    def send_ping(self):
        if not self.running:
            return
        self.ping_event.clear()
        self._send_packet({"type": "ping", "client_time": time.time()})

    def disconnect(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.signals.client_status_changed.emit(False, "ĐÃ NGẮT KẾT NỐI")
        self.signals.system_log.emit("Bạn đã chủ động ngắt kết nối.", "info")


# ==============================================================================
# BỘ QUÉT TỰ ĐỘNG TÌM PHÒNG (AUTO-DISCOVERY SCANNER)
# ==============================================================================
class ClientRoomScanner:
    def __init__(self, signals):
        self.signals = signals
        self.running = False
        self.thread = None
        self.sock = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._scan_loop, daemon=True)
        self.thread.start()

    def _scan_loop(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.bind(("", 2302))
            s.settimeout(1.5)
            self.sock = s
        except Exception:
            return

        while self.running:
            try:
                data, addr = self.sock.recvfrom(2048)
                if not data:
                    continue
                packet = json.loads(data.decode("utf-8", errors="ignore"))
                if packet.get("tag") == "AOE_BEACON":
                    host_name = packet.get("host_name", "Chủ Phòng")
                    host_ip = packet.get("host_ip") or addr[0]
                    port = int(packet.get("port", DEFAULT_PORT))
                    count = int(packet.get("player_count", 1))
                    self.signals.room_discovered.emit(host_name, host_ip, port, count)
            except socket.timeout:
                continue
            except Exception:
                continue

        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


# ==============================================================================
# GIAO DIỆN CHÍNH PYQT6 (DARK GAMING STYLESHEET)
# ==============================================================================
DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #16181d;
    color: #e6edf3;
    font-family: "Segoe UI", "Tahoma", sans-serif;
    font-size: 13px;
}

QGroupBox {
    border: 1px solid #30363d;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: bold;
    color: #f0883e;
    background-color: #1e222b;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 6px;
}

QLineEdit, QComboBox {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #ffffff;
    selection-background-color: #238636;
}
QLineEdit:focus, QComboBox:focus {
    border: 1px solid #58a6ff;
}

QPushButton {
    background-color: #21262d;
    border: 1px solid #363b42;
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: bold;
    color: #c9d1d9;
}
QPushButton:hover {
    background-color: #30363d;
    border-color: #8b949e;
}
QPushButton:pressed {
    background-color: #161b22;
}

QPushButton#btn_primary {
    background-color: #238636;
    border: 1px solid #2ea043;
    color: #ffffff;
}
QPushButton#btn_primary:hover {
    background-color: #2ea043;
}

QPushButton#btn_danger {
    background-color: #da3633;
    border: 1px solid #f85149;
    color: #ffffff;
}
QPushButton#btn_danger:hover {
    background-color: #b62324;
}

QPushButton#btn_launch_game {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #d97706, stop:1 #f59e0b);
    border: 1px solid #fbbf24;
    border-radius: 6px;
    padding: 8px 20px;
    font-size: 14px;
    font-weight: bold;
    color: #ffffff;
}
QPushButton#btn_launch_game:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #f59e0b, stop:1 #fbbf24);
}
QPushButton#btn_launch_game:pressed {
    background-color: #b45309;
}

QPushButton#btn_ready_on {
    background-color: #238636;
    border: 1px solid #2ea043;
    color: #ffffff;
    font-weight: bold;
    font-size: 13px;
    border-radius: 6px;
    padding: 8px 16px;
}
QPushButton#btn_ready_on:hover {
    background-color: #2ea043;
}

QPushButton#btn_ready_off {
    background-color: #21262d;
    border: 1px solid #f0883e;
    color: #f0883e;
    font-weight: bold;
    font-size: 13px;
    border-radius: 6px;
    padding: 8px 16px;
}
QPushButton#btn_ready_off:hover {
    background-color: #30363d;
    color: #ffffff;
}

QPushButton#btn_start_all {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #238636, stop:1 #2ea043);
    border: 1px solid #3fb950;
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 14px;
    font-weight: bold;
    color: #ffffff;
}
QPushButton#btn_start_all:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2ea043, stop:1 #3fb950);
}
QPushButton#btn_start_all:disabled {
    background-color: #21262d;
    border: 1px solid #30363d;
    color: #6e7681;
}

QTabWidget::pane {
    border: 1px solid #30363d;
    border-radius: 8px;
    background-color: #1a1e27;
    top: -1px;
}
QTabBar::tab {
    background: #16181d;
    border: 1px solid #30363d;
    border-bottom: none;
    padding: 10px 24px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    color: #8b949e;
    font-weight: bold;
    font-size: 13px;
}
QTabBar::tab:selected {
    background: #1a1e27;
    border-color: #f0883e;
    border-bottom: 2px solid #1a1e27;
    color: #f0883e;
}
QTabBar::tab:hover:!selected {
    background: #21262d;
    color: #c9d1d9;
}

QTableWidget {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    gridline-color: #21262d;
    color: #e6edf3;
    selection-background-color: #1f6feb;
}
QHeaderView::section {
    background-color: #161b22;
    color: #8b949e;
    padding: 6px;
    border: 1px solid #21262d;
    font-weight: bold;
}

QTextEdit {
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #e6edf3;
    padding: 6px;
    line-height: 1.4;
}

QScrollBar:vertical {
    border: none;
    background: #16181d;
    width: 10px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #30363d;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover {
    background: #58a6ff;
}
"""


class AoEHelperGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("⚔️ AoE 1 Network Helper - Hỗ trợ chơi Đế Chế qua ZeroTier")
        self.resize(1060, 740)
        self.setStyleSheet(DARK_STYLE)

        # Trạng thái backend
        self.signals = NetworkSignals()
        self.host_engine = None
        self.client_engine = None
        self.game_path = self._auto_detect_game_path()
        self.is_client_ready = False
        self.discovered_rooms = {}  # {host_ip: {"name": str, "port": int, "count": int}}

        # Kết nối tín hiệu
        self.signals.client_connected.connect(self.on_client_connected)
        self.signals.client_disconnected.connect(self.on_client_disconnected)
        self.signals.client_ready_changed.connect(self.on_client_ready_changed)
        self.signals.new_chat_message.connect(self.on_new_chat_message)
        self.signals.system_log.connect(self.on_system_log)
        self.signals.client_status_changed.connect(self.on_client_status_changed)
        self.signals.ping_result.connect(self.on_ping_result)
        self.signals.game_started_by_host.connect(self.on_game_started_by_host)
        self.signals.room_discovered.connect(self.on_room_discovered)

        # Timer đo ping tự động cho client
        self.ping_timer = QTimer(self)
        self.ping_timer.timeout.connect(self.trigger_auto_ping)

        # Khởi động bộ quét phòng tự động (UDP Auto-Discovery)
        self.scanner = ClientRoomScanner(self.signals)
        self.scanner.start()

        self._build_ui()

    def closeEvent(self, event):
        if hasattr(self, "scanner") and self.scanner:
            self.scanner.stop()
        if hasattr(self, "host_engine") and self.host_engine:
            self.host_engine.stop()
        if hasattr(self, "client_engine") and self.client_engine:
            self.client_engine.disconnect()
        event.accept()

    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(16, 14, 16, 14)
        main_layout.setSpacing(12)

        # 1. Header tiêu đề
        header_layout = QHBoxLayout()
        title_label = QLabel("⚔️ AOE 1 NETWORK HELPER (ZEROTIER)")
        title_label.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        title_label.setStyleSheet("color: #f0883e; letter-spacing: 1px;")

        subtitle_label = QLabel("Hỗ trợ tạo phòng, kiểm tra kết nối TCP & đo ping cho 3-6 người")
        subtitle_label.setStyleSheet("color: #8b949e; font-size: 12px;")

        header_layout.addWidget(title_label)
        header_layout.addSpacing(16)
        header_layout.addWidget(subtitle_label)
        header_layout.addStretch()

        main_layout.addLayout(header_layout)

        # 2. Main Splitter chia 2 cột: Trái (Cấu hình Host/Client) - Phải (Chat & Log)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)

        # ====================== CỘT TRÁI: TAB HOST / CLIENT ======================
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(10)

        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self._create_host_tab(), "🖥️ MÁY CHỦ (HOST)")
        self.tab_widget.addTab(self._create_client_tab(), "🎮 MÁY KHÁCH (CLIENT)")
        left_layout.addWidget(self.tab_widget)

        splitter.addWidget(left_widget)

        # ====================== CỘT PHẢI: KHUNG CHAT & GHI LOG ===================
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(10)

        # Khung Chat
        chat_group = QGroupBox("💬 PHÒNG CHAT & THÔNG BÁO")
        chat_layout = QVBoxLayout(chat_group)
        chat_layout.setContentsMargins(12, 12, 12, 12)
        chat_layout.setSpacing(8)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setStyleSheet("background-color: #0d1117; border: 1px solid #30363d; font-size: 13px;")
        chat_layout.addWidget(self.chat_display)

        # Phím tắt chat nhanh
        quick_msg_layout = QHBoxLayout()
        quick_msgs = ["Ready!", "Vào game thôi!", "Ping lag quá", "Chờ 1 phút"]
        for qm in quick_msgs:
            btn = QPushButton(qm)
            btn.setStyleSheet("padding: 4px 8px; font-size: 11px; background-color: #21262d; border-radius: 4px;")
            btn.clicked.connect(lambda checked, text=qm: self.send_quick_chat(text))
            quick_msg_layout.addWidget(btn)
        quick_msg_layout.addStretch()
        chat_layout.addLayout(quick_msg_layout)

        # Ô nhập tin nhắn
        msg_input_layout = QHBoxLayout()
        self.msg_input = QLineEdit()
        self.msg_input.setPlaceholderText("Nhập tin nhắn chat (hoặc gõ /help)...")
        self.msg_input.returnPressed.connect(self.on_send_chat)
        
        self.btn_send = QPushButton("Gửi Tin")
        self.btn_send.setObjectName("btn_primary")
        self.btn_send.clicked.connect(self.on_send_chat)

        msg_input_layout.addWidget(self.msg_input)
        msg_input_layout.addWidget(self.btn_send)
        chat_layout.addLayout(msg_input_layout)

        right_layout.addWidget(chat_group)
        splitter.addWidget(right_widget)

        # Tỉ lệ 50:50
        splitter.setSizes([500, 500])
        main_layout.addWidget(splitter, 1)

        # 3. Thanh khởi động nhanh Game Đế Chế (AoE 1) ở đáy cửa sổ
        main_layout.addWidget(self._create_game_launcher_bar())

        # Lời chào ban đầu
        self.append_system_msg("Chào mừng đến với AoE 1 Network Helper! Chọn tab Host hoặc Client để bắt đầu.", "info")

    def _auto_detect_game_path(self):
        """Tự động tìm kiếm file thực thi Empiresx.exe hoặc Empires.exe."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base_dir, "game-de-che-1", "Empiresx.exe"),
            os.path.join(base_dir, "game-de-che-1", "Empires.exe"),
            os.path.join(base_dir, "Empiresx.exe"),
            os.path.join(base_dir, "Empires.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
        return ""

    def _get_short_game_path(self):
        if self.game_path and os.path.exists(self.game_path):
            filename = os.path.basename(self.game_path)
            folder = os.path.basename(os.path.dirname(self.game_path))
            return f"Sẵn sàng: {folder}/{filename}"
        return "Chưa tìm thấy file game (Bấm 'Chọn File...')"

    def _create_game_launcher_bar(self):
        """Tạo thanh điều khiển mở game AoE 1 ở đáy giao diện."""
        frame = QFrame()
        frame.setStyleSheet("""
            QFrame {
                background-color: #1e222b;
                border: 1px solid #30363d;
                border-radius: 8px;
            }
        """)
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        # Biểu tượng game
        icon_label = QLabel("🎮")
        icon_label.setFont(QFont("Segoe UI", 20))
        layout.addWidget(icon_label)

        # Tên & Đường dẫn game
        game_info_layout = QVBoxLayout()
        game_info_layout.setSpacing(2)
        lbl_game_title = QLabel("AGE OF EMPIRES 1 (ĐẾ CHẾ)")
        lbl_game_title.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        lbl_game_title.setStyleSheet("color: #f0883e; letter-spacing: 0.5px;")
        
        self.lbl_game_path = QLabel(self._get_short_game_path())
        self.lbl_game_path.setStyleSheet("color: #8b949e; font-size: 11px;")
        game_info_layout.addWidget(lbl_game_title)
        game_info_layout.addWidget(self.lbl_game_path)
        layout.addLayout(game_info_layout)

        # Nút chọn file game khác nếu muốn
        btn_select_game = QPushButton("📁 Chọn File...")
        btn_select_game.setStyleSheet("padding: 6px 12px; font-size: 12px;")
        btn_select_game.clicked.connect(self.on_select_game_path)
        layout.addWidget(btn_select_game)

        layout.addStretch()

        # Nút Chạy Setupreg (Sửa lỗi mạng)
        btn_setupreg = QPushButton("🛠️ Sửa Lỗi (Setupreg)")
        btn_setupreg.setStyleSheet("padding: 7px 12px; font-size: 12px;")
        btn_setupreg.clicked.connect(self.on_run_setupreg)
        layout.addWidget(btn_setupreg)

        # Nút Hướng dẫn vào phòng
        btn_guide = QPushButton("❓ Hướng Dẫn Vào Game")
        btn_guide.setStyleSheet("padding: 7px 12px; font-size: 12px;")
        btn_guide.clicked.connect(self.on_show_game_guide)
        layout.addWidget(btn_guide)

        # Tùy chọn Chế độ Cửa Sổ HD 1080p + Hiện FPS
        self.chk_hd_mode = QCheckBox("🪟 Cửa Sổ HD 1080p (Hiện FPS)")
        self.chk_hd_mode.setStyleSheet("color: #f0883e; font-weight: bold; font-size: 12px;")
        self.chk_hd_mode.setChecked(True)
        layout.addWidget(self.chk_hd_mode)

        # NÚT MỞ GAME CHÍNH (NỔI BẬT NHẤT)
        self.btn_launch_game = QPushButton("▶️ VÀO GAME ĐẾ CHẾ")
        self.btn_launch_game.setObjectName("btn_launch_game")
        self.btn_launch_game.setMinimumHeight(42)
        self.btn_launch_game.clicked.connect(self.on_launch_game)
        layout.addWidget(self.btn_launch_game)

        return frame

    def on_select_game_path(self):
        """Cho phép người dùng tự duyệt chọn file Empiresx.exe nếu để ở thư mục khác."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file thực thi game Đế Chế (Empiresx.exe hoặc Empires.exe)",
            base_dir,
            "Game Executable (Empires*.exe);;All Files (*.*)"
        )
        if file_path:
            self.game_path = file_path
            self.lbl_game_path.setText(self._get_short_game_path())
            self.append_system_msg(f"Đã cập nhật đường dẫn game: {file_path}", "success")

    def on_launch_game(self):
        """Khởi chạy game Đế Chế 1 và tự động copy IP vào Clipboard."""
        if not self.game_path or not os.path.exists(self.game_path):
            self.game_path = self._auto_detect_game_path()

        if not self.game_path or not os.path.exists(self.game_path):
            QMessageBox.warning(
                self,
                "Không tìm thấy file game",
                "Chưa tìm thấy file Empiresx.exe!\nVui lòng bấm '📁 Chọn File...' để chỉ đường dẫn tới file game của bạn."
            )
            self.on_select_game_path()
            return

        # Tự động copy IP và ghi vào Windows Registry DirectPlay
        copied_ip = ""
        if self.client_engine and self.client_engine.running:
            copied_ip = self.client_engine.host_ip
        elif self.host_engine and self.host_engine.running:
            copied_ip = self.combo_ips.currentData() or self.combo_ips.currentText().split(" ")[0]

        if copied_ip:
            QApplication.clipboard().setText(copied_ip)
            set_directplay_registry_ip(copied_ip)

        try:
            game_dir = os.path.dirname(self.game_path)
            windowed_tool = os.path.join(game_dir, "罗马窗口化.exe")

            # Nếu người dùng tích chọn Cửa Sổ HD và có tool cửa sổ hóa
            if self.chk_hd_mode.isChecked() and os.path.exists(windowed_tool):
                subprocess.Popen([windowed_tool], cwd=game_dir)
                mode_str = " (Chế độ Cửa Sổ HD 1080p + Hiện FPS)"
            else:
                # Mở trực tiếp với độ phân giải cao 1024 và bỏ qua intro video
                subprocess.Popen([self.game_path, "1024", "nostartup"], cwd=game_dir)
                mode_str = " (Độ phân giải 1024x768)"
            
            notice = f"🎮 Đã khởi động Đế Chế{mode_str}!"
            if copied_ip:
                notice += f" (IP Host: {copied_ip} đã nạp sẵn)"
            self.append_system_msg(notice, "success")
            
        except Exception as e:
            QMessageBox.critical(self, "Lỗi mở game", f"Không thể khởi động game:\n{e}")

    def on_run_setupreg(self):
        """Chạy Setupreg.exe trong thư mục game để cập nhật Registry DirectPlay."""
        game_dir = os.path.dirname(self.game_path) if self.game_path else os.path.join(os.path.dirname(os.path.abspath(__file__)), "game-de-che-1")
        setupreg_path = os.path.join(game_dir, "Setupreg.exe")
        if os.path.exists(setupreg_path):
            try:
                subprocess.Popen([setupreg_path], cwd=game_dir)
                self.append_system_msg("🛠️ Đã chạy Setupreg.exe để cập nhật Registry DirectPlay!", "success")
                QMessageBox.information(
                    self,
                    "Setupreg Thành Công",
                    "Đã chạy Setupreg.exe thành công để cập nhật Registry DirectPlay cho AoE 1!"
                )
            except Exception as e:
                QMessageBox.critical(self, "Lỗi", f"Không thể chạy Setupreg: {e}")
        else:
            QMessageBox.warning(self, "Không tìm thấy", f"Không tìm thấy Setupreg.exe trong thư mục:\n{game_dir}")

    def on_show_game_guide(self):
        """Hiển thị cửa sổ hướng dẫn 3 bước kết nối trong game."""
        guide_text = (
            "<h3>🎮 HƯỚNG DẪN KẾT NỐI VÀO PHÒNG TRONG AOE 1:</h3>"
            "<ol>"
            "<li><b>Khởi động Game:</b> Nhấn nút <b>'▶️ VÀO GAME ĐẾ CHẾ'</b> màu cam ở góc dưới.</li>"
            "<li><b>Vào mục nhiều người:</b> Trong menu chính của game, chọn <b>MULTIPLAYER</b>.</li>"
            "<li><b>Chọn kiểu kết nối:</b> Dòng <i>Connection Type</i>, chọn:<br>"
            "👉 <b>Internet TCP/IP Connection For DirectPlay</b> <i>(Tuyệt đối KHÔNG chọn IPX hay Modem)</i>.</li>"
            "<li><b>Nhập tên:</b> Đặt tên bạn ở ô <b>Player Name</b>.</li>"
            "<li><b>Nếu bạn là MÁY CHỦ (Host):</b>"
            "<ul><li>Bấm nút <b>Create</b> để tạo phòng.</li></ul></li>"
            "<li><b>Nếu bạn là MÁY KHÁCH (Client):</b>"
            "<ul>"
            "<li>Bấm nút <b>Show Games</b>.</li>"
            "<li>Nhấn <b>Ctrl + V</b> để dán IP Host <i>(Đã được phần mềm tự copy sẵn vào Clipboard)</i> -> Bấm OK.</li>"
            "<li>Tên phòng của Host sẽ hiện ra, chọn phòng và bấm <b>Join</b> là xong!</li>"
            "</ul></li>"
            "</ol>"
        )
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("📖 Hướng Dẫn Vào Phòng AoE 1")
        msg_box.setTextFormat(Qt.TextFormat.RichText)
        msg_box.setText(guide_text)
        msg_box.exec()

    # --------------------------------------------------------------------------
    # TAB HOST UI
    # --------------------------------------------------------------------------
    def _create_host_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(12)

        # Cài đặt cấu hình Host
        config_group = QGroupBox("CẤU HÌNH PHÒNG MÁY CHỦ")
        config_layout = QVBoxLayout(config_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Tên Host:"))
        self.host_name_input = QLineEdit("Chủ Phòng")
        row1.addWidget(self.host_name_input)

        row1.addWidget(QLabel("Cổng TCP:"))
        self.host_port_input = QLineEdit(str(DEFAULT_PORT))
        self.host_port_input.setFixedWidth(70)
        row1.addWidget(self.host_port_input)
        config_layout.addLayout(row1)

        # Hiển thị IP máy Host
        ip_layout = QHBoxLayout()
        ip_layout.addWidget(QLabel("IP của bạn:"))
        self.combo_ips = QComboBox()
        self.refresh_host_ips()
        ip_layout.addWidget(self.combo_ips, 1)

        btn_copy_ip = QPushButton("📋 Sao chép IP")
        btn_copy_ip.clicked.connect(self.copy_host_ip)
        ip_layout.addWidget(btn_copy_ip)
        config_layout.addLayout(ip_layout)

        # Nút Bắt đầu / Dừng Host
        btn_row = QHBoxLayout()
        self.btn_toggle_host = QPushButton("🚀 Khởi Động Server Host")
        self.btn_toggle_host.setObjectName("btn_primary")
        self.btn_toggle_host.clicked.connect(self.on_toggle_host)
        btn_row.addWidget(self.btn_toggle_host)
        config_layout.addLayout(btn_row)

        layout.addWidget(config_group)

        # Danh sách người chơi tham gia phòng
        players_group = QGroupBox("DANH SÁCH NGƯỜI CHƠI TRONG PHÒNG")
        players_layout = QVBoxLayout(players_group)

        self.table_players = QTableWidget(0, 4)
        self.table_players.setHorizontalHeaderLabels(["Tên Người Chơi", "Trạng Thái", "IP : Port", "Giờ Vào"])
        self.table_players.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_players.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_players.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table_players.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table_players.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        players_layout.addWidget(self.table_players)

        # Nút quản lý người chơi + đếm sẵn sàng
        mgr_row = QHBoxLayout()
        self.btn_kick = QPushButton("🚫 Mời Người Chơi Ra (Kick)")
        self.btn_kick.setObjectName("btn_danger")
        self.btn_kick.clicked.connect(self.on_kick_player)
        mgr_row.addWidget(self.btn_kick)

        self.lbl_ready_count = QLabel("Sẵn sàng: 0 / 0 người")
        self.lbl_ready_count.setStyleSheet("color: #8b949e; font-weight: bold; font-size: 12px;")
        mgr_row.addWidget(self.lbl_ready_count)

        mgr_row.addStretch()

        self.lbl_player_count = QLabel("Tổng số: 0 người chơi")
        self.lbl_player_count.setStyleSheet("color: #8b949e; font-weight: bold;")
        mgr_row.addWidget(self.lbl_player_count)
        players_layout.addLayout(mgr_row)

        # NÚT BẮT ĐẦU TRẬN ĐẤU CỦA HOST (MỞ GAME TẤT CẢ MÁY)
        self.btn_host_start_game = QPushButton("🚀 BẮT ĐẦU TRẬN ĐẤU (MỞ GAME TẤT CẢ CÁC MÁY)")
        self.btn_host_start_game.setObjectName("btn_start_all")
        self.btn_host_start_game.setEnabled(False)
        self.btn_host_start_game.setMinimumHeight(44)
        self.btn_host_start_game.clicked.connect(self.on_host_start_game)
        players_layout.addWidget(self.btn_host_start_game)

        layout.addWidget(players_group, 1)
        return tab

    # --------------------------------------------------------------------------
    # TAB CLIENT UI
    # --------------------------------------------------------------------------
    def _create_client_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(12)

        # 1. Card Tự Động Quét Tìm Phòng (Auto-Discovery)
        discovery_group = QGroupBox("🔍 TỰ ĐỘNG TÌM PHÒNG (AUTO-DISCOVERY)")
        discovery_layout = QVBoxLayout(discovery_group)
        discovery_layout.setSpacing(10)

        disc_header = QHBoxLayout()
        self.lbl_disc_status = QLabel("🟢 Đang quét tìm phòng trong mạng ZeroTier...")
        self.lbl_disc_status.setStyleSheet("color: #3fb950; font-size: 11px; font-weight: bold;")
        disc_header.addWidget(self.lbl_disc_status)

        btn_rescan = QPushButton("🔄 Quét Lại")
        btn_rescan.setStyleSheet("padding: 3px 8px; font-size: 11px;")
        btn_rescan.clicked.connect(self.on_restart_scanner)
        disc_header.addWidget(btn_rescan)
        discovery_layout.addLayout(disc_header)

        # Hàng chọn phòng tự động tìm thấy
        room_row = QHBoxLayout()
        self.combo_discovered_rooms = QComboBox()
        self.combo_discovered_rooms.addItem("-- Đang chờ máy Host mở phòng... --", None)
        self.combo_discovered_rooms.currentIndexChanged.connect(self.on_select_discovered_room)
        room_row.addWidget(self.combo_discovered_rooms, 2)

        self.btn_quick_join = QPushButton("⚡ VÀO PHÒNG NGAY")
        self.btn_quick_join.setObjectName("btn_start_all")
        self.btn_quick_join.setEnabled(False)
        self.btn_quick_join.clicked.connect(self.on_quick_join_room)
        room_row.addWidget(self.btn_quick_join, 1)

        discovery_layout.addLayout(room_row)
        layout.addWidget(discovery_group)

        # 2. Cài đặt kết nối (hoặc nhập thủ công nếu muốn)
        conn_group = QGroupBox("THÔNG TIN KẾT NỐI (TỰ ĐIỀN HOẶC NHẬP TAY)")
        conn_layout = QVBoxLayout(conn_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Tên của bạn:"))
        self.client_name_input = QLineEdit("Player1")
        row1.addWidget(self.client_name_input)
        conn_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("IP Host:"))
        self.client_host_ip_input = QLineEdit()
        self.client_host_ip_input.setPlaceholderText("Tự động điền khi tìm thấy phòng...")
        row2.addWidget(self.client_host_ip_input, 1)

        row2.addWidget(QLabel("Cổng:"))
        self.client_port_input = QLineEdit(str(DEFAULT_PORT))
        self.client_port_input.setFixedWidth(70)
        row2.addWidget(self.client_port_input)
        conn_layout.addLayout(row2)

        # Hàng nút kết nối & Sẵn sàng
        btn_client_row = QHBoxLayout()
        self.btn_toggle_client = QPushButton("🔗 Kết Nối Thủ Công")
        self.btn_toggle_client.setObjectName("btn_primary")
        self.btn_toggle_client.clicked.connect(self.on_toggle_client)
        btn_client_row.addWidget(self.btn_toggle_client, 2)

        self.btn_client_ready = QPushButton("⚡ SẴN SÀNG (READY)")
        self.btn_client_ready.setObjectName("btn_ready_off")
        self.btn_client_ready.setEnabled(False)
        self.btn_client_ready.clicked.connect(self.on_toggle_client_ready)
        btn_client_row.addWidget(self.btn_client_ready, 1)

        conn_layout.addLayout(btn_client_row)

        layout.addWidget(conn_group)

        # Card Trạng thái & Đo độ trễ (Ping)
        status_group = QGroupBox("TRẠNG THÁI MẠNG & ĐỘ TRỄ (PING)")
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(14)

        # Badge trạng thái
        status_row = QHBoxLayout()
        status_row.addWidget(QLabel("Trạng thái:"))
        self.lbl_client_status = QLabel("Chưa kết nối")
        self.lbl_client_status.setStyleSheet(
            "padding: 4px 10px; background-color: #30363d; color: #8b949e; "
            "border-radius: 4px; font-weight: bold;"
        )
        status_row.addWidget(self.lbl_client_status)
        status_row.addStretch()
        status_layout.addLayout(status_row)

        # Khung hiển thị Ping lớn
        ping_box = QFrame()
        ping_box.setStyleSheet(
            "background-color: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 16px;"
        )
        ping_box_layout = QVBoxLayout(ping_box)
        ping_box_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_ping_title = QLabel("ĐỘ TRỄ TỚI HOST (RTT)")
        self.lbl_ping_title.setStyleSheet("color: #8b949e; font-size: 11px; font-weight: bold;")
        self.lbl_ping_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.lbl_ping_val = QLabel("-- ms")
        self.lbl_ping_val.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
        self.lbl_ping_val.setStyleSheet("color: #58a6ff;")
        self.lbl_ping_val.setAlignment(Qt.AlignmentFlag.AlignCenter)

        ping_box_layout.addWidget(self.lbl_ping_title)
        ping_box_layout.addWidget(self.lbl_ping_val)
        status_layout.addWidget(ping_box)

        # Điều khiển Ping
        ping_ctrl_layout = QHBoxLayout()
        self.btn_ping_now = QPushButton("⚡ Đo Ping Ngay")
        self.btn_ping_now.setEnabled(False)
        self.btn_ping_now.clicked.connect(self.on_manual_ping)
        ping_ctrl_layout.addWidget(self.btn_ping_now)

        self.chk_auto_ping = QCheckBox("Tự động đo mỗi 3 giây")
        self.chk_auto_ping.setEnabled(False)
        self.chk_auto_ping.toggled.connect(self.on_toggle_auto_ping)
        ping_ctrl_layout.addWidget(self.chk_auto_ping)
        ping_ctrl_layout.addStretch()

        status_layout.addLayout(ping_ctrl_layout)
        layout.addWidget(status_group)
        layout.addStretch()
        return tab

    # --------------------------------------------------------------------------
    # CÁC HÀM XỬ LÝ SỰ KIỆN MÁY CHỦ (HOST)
    # --------------------------------------------------------------------------
    def refresh_host_ips(self):
        self.combo_ips.clear()
        ips = get_all_ip_addresses()
        for ip in ips:
            note = " (Khuyên dùng - ZeroTier)" if ip.startswith(("10.", "172.", "192.168.19")) else ""
            self.combo_ips.addItem(f"{ip}{note}", ip)

    def copy_host_ip(self):
        current_ip = self.combo_ips.currentData() or self.combo_ips.currentText().split(" ")[0]
        if current_ip:
            QApplication.clipboard().setText(current_ip)
            QMessageBox.information(self, "Đã sao chép", f"Đã copy IP: {current_ip}\nHãy gửi IP này cho các Client!")

    def on_toggle_host(self):
        if self.host_engine and self.host_engine.running:
            # Dừng host
            self.host_engine.stop()
            self.host_engine = None
            self.btn_toggle_host.setText("🚀 Khởi Động Server Host")
            self.btn_toggle_host.setObjectName("btn_primary")
            self.btn_toggle_host.setStyle(self.btn_toggle_host.style())
            self.btn_host_start_game.setEnabled(False)
            self.table_players.setRowCount(0)
            self.lbl_player_count.setText("Tổng số: 0 người chơi")
            self.lbl_ready_count.setText("Sẵn sàng: 0 / 0 người")
            self.host_name_input.setEnabled(True)
            self.host_port_input.setEnabled(True)
            self.tab_widget.setTabEnabled(1, True)
        else:
            # Bật host
            port_text = self.host_port_input.text().strip()
            port = int(port_text) if port_text.isdigit() else DEFAULT_PORT
            name = self.host_name_input.text().strip() or "Chủ Phòng"

            self.host_engine = HostEngine(port=port, host_name=name, signals=self.signals)
            success, msg = self.host_engine.start()
            if success:
                self.btn_toggle_host.setText("🛑 Dừng Server Host")
                self.btn_toggle_host.setObjectName("btn_danger")
                self.btn_toggle_host.setStyle(self.btn_toggle_host.style())
                self.btn_host_start_game.setEnabled(True)
                self.host_name_input.setEnabled(False)
                self.host_port_input.setEnabled(False)
                self.tab_widget.setTabEnabled(1, False)  # Đang làm host thì khóa tab client
            else:
                QMessageBox.critical(self, "Lỗi khởi động", f"Không thể mở cổng {port}:\n{msg}")

    def on_host_start_game(self):
        """Host bấm nút Bắt Đầu: tự động mở game trên máy Host và gửi lệnh mở game cho toàn bộ Client."""
        if not self.host_engine or not self.host_engine.running:
            return

        with self.host_engine.lock:
            total = len(self.host_engine.clients)
            ready = sum(1 for c in self.host_engine.clients.values() if c.get("ready", False))

        if total > 0 and ready < total:
            reply = QMessageBox.question(
                self,
                "Xác nhận Bắt Đầu",
                f"Hiện mới có {ready}/{total} người chơi bấm Sẵn Sàng.\n"
                f"Bạn có chắc muốn BẮT ĐẦU và mở game cho cả phòng ngay bây giờ không?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        current_ip = self.combo_ips.currentData() or self.combo_ips.currentText().split(" ")[0]
        base_dir = os.path.dirname(os.path.abspath(__file__))
        play_sound_alert("start", base_dir)

        # 1. Phát lệnh tới toàn bộ các Client
        self.host_engine.broadcast_start_game(current_ip)

        # 2. Khởi động game trên máy Host
        self.on_launch_game()

        self.append_system_msg(
            f"🚀 ĐÃ BẮT ĐẦU TRẬN ĐẤU! Game đang tự động mở trên tất cả các máy (IP Host: {current_ip}).", "success"
        )

    def on_kick_player(self):
        if not self.host_engine or not self.host_engine.running:
            return
        selected_rows = self.table_players.selectedIndexes()
        if not selected_rows:
            QMessageBox.warning(self, "Thông báo", "Vui lòng chọn 1 người chơi trong bảng để mời ra!")
            return
        row = selected_rows[0].row()
        player_name = self.table_players.item(row, 0).text()
        
        reply = QMessageBox.question(
            self, "Xác nhận", f"Bạn có chắc muốn mời người chơi '{player_name}' ra khỏi phòng?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.host_engine.kick_player(player_name)

    # --------------------------------------------------------------------------
    # CÁC HÀM XỬ LÝ SỰ KIỆN MÁY KHÁCH (CLIENT)
    # --------------------------------------------------------------------------
    def on_toggle_client(self):
        if self.client_engine and self.client_engine.running:
            # Ngắt kết nối
            self.client_engine.disconnect()
            self.client_engine = None
            self.btn_toggle_client.setText("🔗 Kiểm Tra & Kết Nối")
            self.btn_toggle_client.setObjectName("btn_primary")
            self.btn_toggle_client.setStyle(self.btn_toggle_client.style())
            self.client_name_input.setEnabled(True)
            self.client_host_ip_input.setEnabled(True)
            self.client_port_input.setEnabled(True)
            self.btn_client_ready.setEnabled(False)
            self.is_client_ready = False
            self.btn_client_ready.setText("⚡ SẴN SÀNG (READY)")
            self.btn_client_ready.setObjectName("btn_ready_off")
            self.btn_client_ready.setStyle(self.btn_client_ready.style())
            self.btn_ping_now.setEnabled(False)
            self.chk_auto_ping.setEnabled(False)
            self.chk_auto_ping.setChecked(False)
            self.lbl_ping_val.setText("-- ms")
            self.lbl_ping_val.setStyleSheet("color: #8b949e;")
            self.tab_widget.setTabEnabled(0, True)
        else:
            host_ip = self.client_host_ip_input.text().strip()
            if not host_ip:
                QMessageBox.warning(self, "Thiếu thông tin", "Vui lòng nhập IP ZeroTier của máy Host!")
                self.client_host_ip_input.setFocus()
                return

            port_text = self.client_port_input.text().strip()
            port = int(port_text) if port_text.isdigit() else DEFAULT_PORT
            name = self.client_name_input.text().strip() or "Khách"

            self.client_engine = ClientEngine(
                host_ip=host_ip, port=port, player_name=name, signals=self.signals
            )

            # Chạy kết nối trong thread phụ để tránh đơ giao diện
            self.btn_toggle_client.setEnabled(False)
            self.btn_toggle_client.setText("Đang kết nối...")

            def do_connect():
                success, _ = self.client_engine.connect()
                # Sau khi xong, update lại trạng thái nút ở main thread
                QTimer.singleShot(0, lambda: self._on_connect_finished(success))

            threading.Thread(target=do_connect, daemon=True).start()

    def _on_connect_finished(self, success):
        self.btn_toggle_client.setEnabled(True)
        if success:
            self.btn_toggle_client.setText("❌ Ngắt Kết Nối")
            self.btn_toggle_client.setObjectName("btn_danger")
            self.btn_toggle_client.setStyle(self.btn_toggle_client.style())
            self.client_name_input.setEnabled(False)
            self.client_host_ip_input.setEnabled(False)
            self.client_port_input.setEnabled(False)
            self.btn_client_ready.setEnabled(True)
            self.is_client_ready = False
            self.btn_client_ready.setText("⚡ SẴN SÀNG (READY)")
            self.btn_client_ready.setObjectName("btn_ready_off")
            self.btn_client_ready.setStyle(self.btn_client_ready.style())
            self.btn_ping_now.setEnabled(True)
            self.chk_auto_ping.setEnabled(True)
            self.tab_widget.setTabEnabled(0, False)  # Đang là client thì khóa tab host
        else:
            self.btn_toggle_client.setText("🔗 Kiểm Tra & Kết Nối")
            self.btn_toggle_client.setObjectName("btn_primary")
            self.btn_toggle_client.setStyle(self.btn_toggle_client.style())
            self.btn_client_ready.setEnabled(False)
            self.client_engine = None

    def on_toggle_client_ready(self):
        """Khách bấm nút Sẵn Sàng / Hủy Sẵn Sàng."""
        if not self.client_engine or not self.client_engine.running:
            return

        self.is_client_ready = not self.is_client_ready
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        if self.is_client_ready:
            self.btn_client_ready.setText("✅ ĐÃ SẴN SÀNG (Bấm lại để hủy)")
            self.btn_client_ready.setObjectName("btn_ready_on")
            self.btn_client_ready.setStyle(self.btn_client_ready.style())
            self.client_engine.send_ready(True)
            play_sound_alert("ready", base_dir)
            self.append_system_msg("Bạn đã bấm SẴN SÀNG! Đang chờ Chủ phòng bắt đầu trận đấu...", "success")
        else:
            self.btn_client_ready.setText("⚡ SẴN SÀNG (READY)")
            self.btn_client_ready.setObjectName("btn_ready_off")
            self.btn_client_ready.setStyle(self.btn_client_ready.style())
            self.client_engine.send_ready(False)
            self.append_system_msg("Bạn đã hủy trạng thái Sẵn Sàng.", "info")

    def on_game_started_by_host(self, host_ip):
        """Chủ phòng đã bấm Bắt Đầu: tự động mở game và copy IP Host."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        play_sound_alert("start", base_dir)

        # 1. Tự động copy IP Host vào clipboard
        if host_ip:
            QApplication.clipboard().setText(host_ip)

        self.append_system_msg(
            f"🚀 CHỦ PHÒNG ĐÃ BẮT ĐẦU TRẬN ĐẤU! Game đang tự động mở...", "success"
        )

        # 2. Tự động mở game Empiresx.exe
        self.on_launch_game()

        # 3. Hiện hộp thoại thông báo nổi bật cho Client
        popup = QMessageBox(self)
        popup.setWindowTitle("🚀 Trận Đấu Bắt Đầu!")
        popup.setTextFormat(Qt.TextFormat.RichText)
        popup.setText(
            f"<h3>⚔️ CHỦ PHÒNG ĐÃ PHÁT LỆNH BẮT ĐẦU!</h3>"
            f"<p>Game Đế Chế đang tự động mở trên máy của bạn...</p>"
            f"<p><b>IP Host:</b> <span style='color: #58a6ff; font-size: 15px;'><b>{host_ip}</b></span> (Đã tự động copy vào Clipboard!)</p>"
            f"<hr>"
            f"<p><b>3 BƯỚC VÀO TRẬN ĐẤU:</b></p>"
            f"<ol>"
            f"<li>Trong game, bấm <b>MULTIPLAYER</b>.</li>"
            f"<li>Chọn <b>Internet TCP/IP Connection For DirectPlay</b>.</li>"
            f"<li>Bấm <b>Show Games</b> -> Nhấn <b>Ctrl + V</b> để dán IP -> Bấm <b>Join</b> là vào chiến!</li>"
            f"</ol>"
        )
        popup.setIcon(QMessageBox.Icon.Information)
        popup.exec()

    def on_client_ready_changed(self, name, is_ready):
        """Host nhận thông báo trạng thái sẵn sàng của một client."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if is_ready:
            play_sound_alert("ready", base_dir)

        # Cập nhật trong bảng table_players (cột 1: Trạng Thái)
        for r in range(self.table_players.rowCount()):
            if self.table_players.item(r, 0).text() == name:
                item = QTableWidgetItem("🟢 ĐÃ SẴN SÀNG" if is_ready else "⏳ Chờ sẵn sàng")
                item.setForeground(QColor("#3fb950" if is_ready else "#8b949e"))
                self.table_players.setItem(r, 1, item)
                break

        # Cập nhật số đếm
        if self.host_engine:
            with self.host_engine.lock:
                total = len(self.host_engine.clients)
                ready = sum(1 for c in self.host_engine.clients.values() if c.get("ready", False))
            self.lbl_ready_count.setText(f"Sẵn sàng: {ready} / {total} người")
            if ready == total and total > 0:
                self.lbl_ready_count.setStyleSheet("color: #3fb950; font-weight: bold; font-size: 12px;")
            else:
                self.lbl_ready_count.setStyleSheet("color: #d29922; font-weight: bold; font-size: 12px;")

    def on_room_discovered(self, host_name, host_ip, port, count):
        """Khi bộ quét phát hiện thấy một phòng Host đang mở trong mạng ZeroTier."""
        first_time = (host_ip not in self.discovered_rooms)
        self.discovered_rooms[host_ip] = {"name": host_name, "port": port, "count": count}

        # Cập nhật danh sách ComboBox
        self.combo_discovered_rooms.blockSignals(True)
        self.combo_discovered_rooms.clear()
        for idx, (ip, info) in enumerate(self.discovered_rooms.items()):
            label = f"👑 {info['name']} (IP: {ip}:{info['port']}) - [{info['count']} người]"
            self.combo_discovered_rooms.addItem(label, (ip, info['port']))

        self.combo_discovered_rooms.setCurrentIndex(0)
        self.combo_discovered_rooms.blockSignals(False)

        # Tự động điền luôn IP và Cổng vào các ô kết nối
        self.client_host_ip_input.setText(host_ip)
        self.client_port_input.setText(str(port))
        
        # Bật nút Vào Phòng Ngay nếu chưa kết nối
        if not (self.client_engine and self.client_engine.running):
            self.btn_quick_join.setEnabled(True)

        if first_time:
            self.lbl_disc_status.setText(f"🎉 Đã tìm thấy phòng của '{host_name}'!")
            self.lbl_disc_status.setStyleSheet("color: #3fb950; font-size: 11px; font-weight: bold;")
            self.append_system_msg(
                f"🎉 TỰ ĐỘNG TÌM THẤY PHÒNG: '{host_name}' ({host_ip}:{port})! Bấm 'Vào Phòng Ngay' để kết nối.",
                "success"
            )

    def on_select_discovered_room(self, idx):
        """Khi người dùng chọn một phòng khác trong danh sách phòng quét được."""
        data = self.combo_discovered_rooms.currentData()
        if data:
            host_ip, port = data
            self.client_host_ip_input.setText(host_ip)
            self.client_port_input.setText(str(port))
            if not (self.client_engine and self.client_engine.running):
                self.btn_quick_join.setEnabled(True)

    def on_quick_join_room(self):
        """Bấm nút Vào Phòng Ngay: kết nối 1-click không cần gõ hay copy bất kỳ IP nào."""
        data = self.combo_discovered_rooms.currentData()
        if data:
            host_ip, port = data
            self.client_host_ip_input.setText(host_ip)
            self.client_port_input.setText(str(port))
        self.on_toggle_client()

    def on_restart_scanner(self):
        """Bấm nút Quét Lại phòng chơi."""
        self.discovered_rooms.clear()
        self.combo_discovered_rooms.clear()
        self.combo_discovered_rooms.addItem("-- Đang quét tìm phòng... --", None)
        self.btn_quick_join.setEnabled(False)
        self.lbl_disc_status.setText("🟢 Đang quét tìm phòng trong mạng ZeroTier...")
        self.lbl_disc_status.setStyleSheet("color: #3fb950; font-size: 11px; font-weight: bold;")
        if hasattr(self, "scanner") and self.scanner:
            self.scanner.stop()
        self.scanner = ClientRoomScanner(self.signals)
        self.scanner.start()

    def on_manual_ping(self):
        if self.client_engine and self.client_engine.running:
            self.client_engine.send_ping()

    def on_toggle_auto_ping(self, checked):
        if checked:
            self.ping_timer.start(3000)
            self.trigger_auto_ping()
        else:
            self.ping_timer.stop()

    def trigger_auto_ping(self):
        if self.client_engine and self.client_engine.running:
            self.client_engine.send_ping()

    # --------------------------------------------------------------------------
    # CHAT & LOGGING
    # --------------------------------------------------------------------------
    def on_send_chat(self):
        text = self.msg_input.text().strip()
        if not text:
            return

        if self.host_engine and self.host_engine.running:
            self.host_engine.send_chat(text)
            self.msg_input.clear()
        elif self.client_engine and self.client_engine.running:
            self.client_engine.send_chat(text)
            self.msg_input.clear()
        else:
            QMessageBox.information(
                self, "Chưa vào phòng", "Bạn cần Khởi động Server (Host) hoặc Kết nối tới Host (Client) để chat!"
            )

    def send_quick_chat(self, text):
        self.msg_input.setText(text)
        self.on_send_chat()

    def append_system_msg(self, msg, level="info"):
        color = "#8b949e"
        if level == "success":
            color = "#3fb950"
        elif level == "warning":
            color = "#d29922"
        elif level == "error":
            color = "#f85149"

        t = get_current_time()
        html = f"<div style='color: {color}; margin: 3px 0;'><b>[{t}]</b> ℹ️ {msg}</div>"
        self.chat_display.append(html)
        self.chat_display.moveCursor(QTextCursor.MoveOperation.End)

    # --------------------------------------------------------------------------
    # SLOTS NHẬN TÍN HIỆU TỪ BACKEND
    # --------------------------------------------------------------------------
    def on_client_connected(self, name, ip_port, join_time):
        row = self.table_players.rowCount()
        self.table_players.insertRow(row)
        self.table_players.setItem(row, 0, QTableWidgetItem(name))
        
        status_item = QTableWidgetItem("⏳ Chờ sẵn sàng")
        status_item.setForeground(QColor("#8b949e"))
        self.table_players.setItem(row, 1, status_item)

        self.table_players.setItem(row, 2, QTableWidgetItem(ip_port))
        self.table_players.setItem(row, 3, QTableWidgetItem(join_time))
        self.lbl_player_count.setText(f"Tổng số: {self.table_players.rowCount()} người chơi")

        if self.host_engine:
            with self.host_engine.lock:
                total = len(self.host_engine.clients)
                ready = sum(1 for c in self.host_engine.clients.values() if c.get("ready", False))
            self.lbl_ready_count.setText(f"Sẵn sàng: {ready} / {total} người")

    def on_client_disconnected(self, name, ip):
        for r in range(self.table_players.rowCount()):
            if self.table_players.item(r, 0).text() == name:
                self.table_players.removeRow(r)
                break
        self.lbl_player_count.setText(f"Tổng số: {self.table_players.rowCount()} người chơi")
        if self.host_engine:
            with self.host_engine.lock:
                total = len(self.host_engine.clients)
                ready = sum(1 for c in self.host_engine.clients.values() if c.get("ready", False))
            self.lbl_ready_count.setText(f"Sẵn sàng: {ready} / {total} người")

    def on_new_chat_message(self, sender, message, t):
        is_me = "Bạn" in sender
        badge_color = "#238636" if is_me else ("#d29922" if "Host" in sender else "#1f6feb")
        sender_color = "#ffffff"

        html = (
            f"<div style='margin: 4px 0;'>"
            f"<span style='color: #8b949e; font-size: 11px;'>[{t}]</span> "
            f"<span style='background-color: {badge_color}; color: {sender_color}; "
            f"padding: 2px 6px; border-radius: 4px; font-weight: bold;'>{sender}</span>: "
            f"<span style='color: #e6edf3;'>{message}</span>"
            f"</div>"
        )
        self.chat_display.append(html)
        self.chat_display.moveCursor(QTextCursor.MoveOperation.End)

    def on_system_log(self, message, level):
        self.append_system_msg(message, level)

    def on_client_status_changed(self, is_connected, status_text):
        if is_connected:
            self.lbl_client_status.setText(status_text)
            self.lbl_client_status.setStyleSheet(
                "padding: 4px 10px; background-color: #238636; color: #ffffff; "
                "border-radius: 4px; font-weight: bold;"
            )
        else:
            self.lbl_client_status.setText(status_text)
            self.lbl_client_status.setStyleSheet(
                "padding: 4px 10px; background-color: #da3633; color: #ffffff; "
                "border-radius: 4px; font-weight: bold;"
            )
            self.btn_toggle_client.setText("🔗 Kiểm Tra & Kết Nối")
            self.btn_toggle_client.setObjectName("btn_primary")
            self.btn_toggle_client.setStyle(self.btn_toggle_client.style())
            self.client_name_input.setEnabled(True)
            self.client_host_ip_input.setEnabled(True)
            self.client_port_input.setEnabled(True)
            self.btn_client_ready.setEnabled(False)
            self.is_client_ready = False
            self.btn_client_ready.setText("⚡ SẴN SÀNG (READY)")
            self.btn_client_ready.setObjectName("btn_ready_off")
            self.btn_client_ready.setStyle(self.btn_client_ready.style())
            self.btn_ping_now.setEnabled(False)
            self.chk_auto_ping.setEnabled(False)
            self.chk_auto_ping.setChecked(False)
            self.tab_widget.setTabEnabled(0, True)

    def on_ping_result(self, latency):
        color = "#3fb950" if latency < 60 else ("#d29922" if latency < 130 else "#f85149")
        self.lbl_ping_val.setText(f"{latency:.1f} ms")
        self.lbl_ping_val.setStyleSheet(f"color: {color};")


# ==============================================================================
# HÀM CHÍNH (MAIN)
# ==============================================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = AoEHelperGUI()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
