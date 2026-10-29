"""
Chương trình: aoe_helper.py
Mục đích: Hỗ trợ kết nối, kiểm tra mạng, chat và đo ping cho nhóm chơi Age of Empires 1 (AoE 1) qua ZeroTier.
Tác giả: Hỗ trợ cộng đồng AoE
Yêu cầu: Python 3.x (chỉ dùng thư viện chuẩn)
"""

import os
import sys
import subprocess

# Tự động chuyển sang môi trường ảo .venv nếu đang chạy bằng Python hệ thống
def _ensure_venv():
    if getattr(sys, "frozen", False):
        return
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

import time
import json
import socket
import threading
import argparse
from datetime import datetime

# Đảm bảo console Windows in được tiếng Việt có dấu mà không bị lỗi Unicode
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Cổng mặc định (theo yêu cầu là 2300, có thể cấu hình)
DEFAULT_PORT = 2300
BUFFER_SIZE = 4096


def get_current_time():
    """Lấy thời gian hiện tại định dạng Giờ:Phút:Giây."""
    return datetime.now().strftime("%H:%M:%S")


def get_all_ip_addresses():
    """
    Lấy danh sách tất cả các địa chỉ IPv4 của máy hiện tại.
    Hữu ích để người chơi tìm đúng IP ảo được ZeroTier cấp phát.
    """
    ip_list = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                ip_list.append(ip)
    except Exception:
        pass

    # Nếu không tìm thấy qua gethostbyname_ex, thử tạo kết nối ảo để lấy IP chính
    if not ip_list:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip_list.append(s.getsockname()[0])
            s.close()
        except Exception:
            ip_list.append("127.0.0.1")

    return list(dict.fromkeys(ip_list))


# ==============================================================================
# PHẦN 1: MÁY CHỦ (HOST)
# ==============================================================================
class AoEHost:
    def __init__(self, port=DEFAULT_PORT, host_name="Host"):
        self.port = port
        self.host_name = host_name
        self.running = True
        self.server_socket = None
        # Danh sách lưu các client: {socket: {"name": str, "addr": tuple, "join_time": str}}
        self.clients = {}
        self.lock = threading.Lock()

    def start(self):
        """Khởi động máy chủ host."""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(("0.0.0.0", self.port))
            self.server_socket.listen(10)
        except Exception as e:
            print(f"[{get_current_time()}] [LỖI] Không thể mở cổng {self.port}: {e}")
            print("Gợi ý: Kiểm tra xem cổng này có đang bị ứng dụng khác hoặc AoE chiếm dụng không.")
            return

        print("\n" + "=" * 60)
        print("          AOE 1 NETWORK HELPER - CHẾ ĐỘ HOST")
        print("=" * 60)
        print(f"[{get_current_time()}] Máy chủ đang lắng nghe trên cổng TCP: {self.port}")
        
        # Hiển thị các IP của máy host để các bạn cùng phòng ZeroTier nhập vào
        print("\n[DANH SÁCH ĐỊA CHỈ IP CỦA MÁY HOST]:")
        ips = get_all_ip_addresses()
        for idx, ip in enumerate(ips, 1):
            # Nhận diện sơ bộ IP ZeroTier thường có dạng mạng riêng (10.x, 172.x, 192.168.19x...)
            note = " <- (Khả năng cao là IP ZeroTier)" if ip.startswith(("10.", "172.", "192.168.19")) else ""
            print(f"  {idx}. {ip}{note}")
        print("-> Hãy copy đúng IP ZeroTier của bạn gửi cho các máy Client kết nối!\n")
        print("Lệnh có sẵn: gõ văn bản để chat, /list (xem phòng), /kick <tên>, /help, /exit (thoát)\n" + "-" * 60)

        # Thread chấp nhận kết nối từ các client
        accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        accept_thread.start()

        # Luồng chính xử lý nhập liệu chat và lệnh từ Host
        self._host_input_loop()

    def _accept_loop(self):
        """Vòng lặp chấp nhận các kết nối mới từ client."""
        while self.running:
            try:
                client_sock, addr = self.server_socket.accept()
                client_thread = threading.Thread(
                    target=self._handle_client, args=(client_sock, addr), daemon=True
                )
                client_thread.start()
            except Exception:
                break

    def _handle_client(self, client_sock, addr):
        """Xử lý giao tiếp với từng client kết nối tới."""
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

                    # Gói tin đăng ký tên khi mới kết nối
                    if msg_type == "join":
                        client_name = packet.get("name", client_name).strip()
                        join_time = get_current_time()
                        with self.lock:
                            self.clients[client_sock] = {
                                "name": client_name,
                                "addr": addr,
                                "join_time": join_time,
                            }
                        registered = True

                        # Ghi log kết nối
                        print(f"[{join_time}] [KẾT NỐI MỚI] Người chơi '{client_name}' ({addr[0]}:{addr[1]}) đã tham gia phòng.")

                        # Gửi thông báo chào mừng và danh sách người chơi cho client mới
                        welcome_msg = {
                            "type": "system",
                            "msg": f"Chào mừng {client_name}! Bạn đã kết nối thành công tới Host ({self.host_name}).",
                        }
                        self._send_packet(client_sock, welcome_msg)

                        # Thông báo cho tất cả người chơi khác
                        self._broadcast(
                            {"type": "system", "msg": f"'{client_name}' ({addr[0]}) đã vào phòng."},
                            exclude_sock=client_sock,
                        )

                    # Gói tin tin nhắn chat
                    elif msg_type == "chat":
                        sender = packet.get("name", client_name)
                        msg_text = packet.get("text", "")
                        timestamp = get_current_time()
                        print(f"[{timestamp}] [CHAT] {sender}: {msg_text}")
                        # Chuyển tiếp tin nhắn tới tất cả client khác
                        self._broadcast({
                            "type": "chat",
                            "name": sender,
                            "text": msg_text,
                            "time": timestamp
                        }, exclude_sock=client_sock)

                    # Gói tin đo độ trễ (Ping)
                    elif msg_type == "ping":
                        # Phản hồi ngay gói pong kèm timestamp gốc để client tự tính độ trễ
                        pong_packet = {
                            "type": "pong",
                            "client_time": packet.get("client_time", 0)
                        }
                        self._send_packet(client_sock, pong_packet)

        except (ConnectionResetError, ConnectionAbortedError, socket.error):
            pass
        finally:
            # Xử lý khi client ngắt kết nối
            with self.lock:
                info = self.clients.pop(client_sock, None)

            try:
                client_sock.close()
            except Exception:
                pass

            if info and registered:
                left_time = get_current_time()
                name = info["name"]
                ip_str = info["addr"][0]
                print(f"[{left_time}] [NGẮT KẾT NỐI] Người chơi '{name}' ({ip_str}) đã rời phòng.")
                self._broadcast({"type": "system", "msg": f"'{name}' đã rời phòng."})

    def _send_packet(self, sock, packet):
        """Gửi 1 gói tin JSON (kèm ký tự xuống dòng) qua socket."""
        try:
            data = (json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8")
            sock.sendall(data)
        except Exception:
            pass

    def _broadcast(self, packet, exclude_sock=None):
        """Gửi gói tin tới tất cả các client đang kết nối."""
        with self.lock:
            sockets = list(self.clients.keys())
        for sock in sockets:
            if sock != exclude_sock:
                self._send_packet(sock, packet)

    def _host_input_loop(self):
        """Xử lý lệnh và tin nhắn do người làm Host gõ."""
        try:
            while self.running:
                user_input = sys.stdin.readline()
                if not user_input:
                    break
                text = user_input.strip()
                if not text:
                    continue

                if text.lower() == "/exit":
                    print(f"[{get_current_time()}] Đang đóng phòng host...")
                    self.stop()
                    break

                elif text.lower() == "/help":
                    print("\n--- HƯỚNG DẪN LỆNH HOST ---")
                    print("  /list        : Xem danh sách các thành viên trong phòng")
                    print("  /kick <tên>  : Mời một người chơi ra khỏi phòng")
                    print("  /exit        : Tắt máy chủ và thoát")
                    print("  Gõ chữ thường: Gửi tin nhắn chat tới toàn bộ người chơi\n")

                elif text.lower() == "/list":
                    with self.lock:
                        print(f"\n--- DANH SÁCH THÀNH VIÊN TRONG PHÒNG ({len(self.clients) + 1} người) ---")
                        print(f" * [HOST] {self.host_name} (Máy hiện tại)")
                        for idx, (sock, info) in enumerate(self.clients.items(), 1):
                            addr = info['addr']
                            print(f"  {idx}. {info['name']} - IP: {addr[0]}:{addr[1]} (Vào lúc {info['join_time']})")
                        print("-" * 50 + "\n")

                elif text.lower().startswith("/kick "):
                    target_name = text[6:].strip()
                    kicked = False
                    with self.lock:
                        for s, info in list(self.clients.items()):
                            if info["name"].lower() == target_name.lower():
                                self._send_packet(s, {"type": "system", "msg": "Bạn đã bị Host mời ra khỏi phòng."})
                                try:
                                    s.close()
                                except Exception:
                                    pass
                                kicked = True
                                break
                    if kicked:
                        print(f"[{get_current_time()}] Đã ngắt kết nối với người chơi '{target_name}'.")
                    else:
                        print(f"[{get_current_time()}] Không tìm thấy người chơi nào có tên '{target_name}'.")

                else:
                    # Host chat với mọi người
                    timestamp = get_current_time()
                    print(f"[{timestamp}] [CHAT] (Bạn) {self.host_name}: {text}")
                    self._broadcast({
                        "type": "chat",
                        "name": f"(Host) {self.host_name}",
                        "text": text,
                        "time": timestamp
                    })
        except (KeyboardInterrupt, EOFError):
            print("\nĐang dừng phòng...")
            self.stop()

    def stop(self):
        """Dừng host và đóng tất cả kết nối."""
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


# ==============================================================================
# PHẦN 2: MÁY KHÁCH (CLIENT)
# ==============================================================================
class AoEClient:
    def __init__(self, host_ip, port=DEFAULT_PORT, player_name="Client"):
        self.host_ip = host_ip
        self.port = port
        self.player_name = player_name
        self.sock = None
        self.running = True
        self.ping_sent_time = None
        self.ping_event = threading.Event()

    def connect(self):
        """Kiểm tra và thực hiện kết nối TCP tới máy host."""
        print(f"\n[{get_current_time()}] Đang kết nối tới Host: {self.host_ip}:{self.port} ...")
        
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.settimeout(5.0)  # Timeout 5 giây để kiểm tra kết nối

        start_check = time.time()
        try:
            test_sock.connect((self.host_ip, self.port))
            latency = (time.time() - start_check) * 1000
            print(f"[{get_current_time()}] [TRẠNG THÁI: OK] Kết nối TCP thành công! (Bắt tay ban đầu: {latency:.1f} ms)")
            self.sock = test_sock
            self.sock.settimeout(None)  # Trở lại chế độ blocking bình thường
        except socket.timeout:
            print(f"[{get_current_time()}] [TRẠNG THÁI: THẤT BẠI] Kết nối quá thời gian chờ (Timeout sau 5s).")
            self._print_troubleshooting()
            return False
        except ConnectionRefusedError:
            print(f"[{get_current_time()}] [TRẠNG THÁI: THẤT BẠI] Máy host từ chối kết nối (Connection Refused).")
            print("Gợi ý: Hãy chắc chắn máy host đã bật chế độ Host trên script này.")
            return False
        except Exception as e:
            print(f"[{get_current_time()}] [TRẠNG THÁI: THẤT BẠI] Không thể kết nối tới Host: {e}")
            self._print_troubleshooting()
            return False

        # Gửi thông tin đăng ký tên người chơi
        join_packet = {
            "type": "join",
            "name": self.player_name
        }
        self._send_packet(join_packet)
        return True

    def _print_troubleshooting(self):
        """In gợi ý khắc phục khi không thể kết nối."""
        print("\n--- CÁC BƯỚC KIỂM TRA KHẮC PHỤC ---")
        print("1. Cả 2 máy đã bật ZeroTier và tham gia cùng Network ID chưa?")
        print("2. Đã kiểm tra trạng thái ZeroTier là 'OK' chưa?")
        print("3. Kiểm tra xem máy Host đã tắt Windows Firewall hoặc cho phép cổng TCP này chưa.")
        print(f"4. Kiểm tra IP '{self.host_ip}' có đúng là IP ZeroTier của máy Host không.\n")

    def start(self):
        """Bắt đầu vòng lặp nhận tin nhắn và nhập lệnh."""
        if not self.connect():
            return

        print("\n" + "=" * 60)
        print("          AOE 1 NETWORK HELPER - CHẾ ĐỘ CLIENT")
        print("=" * 60)
        print(f"Tên người chơi: {self.player_name}")
        print("Lệnh hỗ trợ: /ping (đo độ trễ), /help (hướng dẫn), /exit (thoát)")
        print("Gõ bất kỳ dòng chữ nào và nhấn Enter để chat cùng phòng.\n" + "-" * 60)

        # Thread nhận dữ liệu từ Host
        recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        recv_thread.start()

        # Luồng chính nhập tin nhắn
        self._input_loop()

    def _send_packet(self, packet):
        """Gửi gói tin JSON tới Host."""
        try:
            data = (json.dumps(packet, ensure_ascii=False) + "\n").encode("utf-8")
            self.sock.sendall(data)
        except Exception:
            pass

    def _recv_loop(self):
        """Nhận và xử lý các gói tin từ máy host."""
        buffer = ""
        while self.running:
            try:
                data = self.sock.recv(BUFFER_SIZE)
                if not data:
                    print(f"\n[{get_current_time()}] [CẢNH BÁO] Đã mất kết nối tới máy chủ Host.")
                    self.running = False
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
                        t = packet.get("time", get_current_time())
                        sender = packet.get("name", "Người lạ")
                        msg = packet.get("text", "")
                        print(f"[{t}] [CHAT] {sender}: {msg}")

                    elif msg_type == "system":
                        print(f"[{get_current_time()}] [HỆ THỐNG] {packet.get('msg')}")

                    elif msg_type == "pong":
                        # Nhận phản hồi Ping từ host
                        sent_time = packet.get("client_time", 0)
                        now = time.time()
                        rtt_ms = (now - sent_time) * 1000
                        print(f"[{get_current_time()}] [PING] Độ trễ tới Host: {rtt_ms:.1f} ms")
                        self.ping_event.set()

            except (ConnectionResetError, ConnectionAbortedError, socket.error):
                if self.running:
                    print(f"\n[{get_current_time()}] [CẢNH BÁO] Kết nối tới Host bị gián đoạn.")
                self.running = False
                break

    def ping_host(self):
        """Gửi yêu cầu ping tới host để đo độ trễ round-trip (RTT)."""
        if not self.running:
            print("Không thể ping vì chưa kết nối tới host.")
            return

        self.ping_event.clear()
        start_time = time.time()
        self._send_packet({"type": "ping", "client_time": start_time})

        # Đợi tối đa 3 giây để nhận phản hồi pong
        received = self.ping_event.wait(timeout=3.0)
        if not received:
            print(f"[{get_current_time()}] [PING] Hết thời gian chờ (Request timed out).")

    def _input_loop(self):
        """Vòng lặp đọc dữ liệu nhập từ bàn phím."""
        try:
            while self.running:
                user_input = sys.stdin.readline()
                if not user_input:
                    break
                text = user_input.strip()
                if not text:
                    continue

                if text.lower() == "/exit":
                    print("Đang ngắt kết nối...")
                    self.stop()
                    break

                elif text.lower() == "/ping":
                    self.ping_host()

                elif text.lower() == "/help":
                    print("\n--- HƯỚNG DẪN LỆNH CLIENT ---")
                    print("  /ping : Gửi gói ping kiểm tra độ trễ (latency) tới Host")
                    print("  /exit : Rời phòng và thoát chương trình")
                    print("  Gõ chữ: Gửi tin nhắn chat tới toàn phòng\n")

                else:
                    # Gửi tin nhắn chat
                    timestamp = get_current_time()
                    print(f"[{timestamp}] [CHAT] (Bạn) {self.player_name}: {text}")
                    self._send_packet({
                        "type": "chat",
                        "name": self.player_name,
                        "text": text
                    })
        except (KeyboardInterrupt, EOFError):
            print("\nĐang thoát...")
            self.stop()

    def stop(self):
        """Đóng kết nối."""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass


# ==============================================================================
# HÀM MAIN: KHỞI TẠO VÀ ĐIỀU PHỐI CHẾ ĐỘ
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="AoE 1 Network Helper - Công cụ hỗ trợ kết nối, chat và đo ping chơi Đế Chế qua ZeroTier"
    )
    subparsers = parser.add_subparsers(dest="mode", help="Chế độ chạy (host hoặc client)")

    # Tham số cho chế độ host
    host_parser = subparsers.add_parser("host", help="Chạy ở chế độ Host (máy chủ phòng)")
    host_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Cổng TCP lắng nghe (mặc định: {DEFAULT_PORT})")
    host_parser.add_argument("--name", type=str, default="Chủ Phòng", help="Tên của máy Host")

    # Tham số cho chế độ client
    client_parser = subparsers.add_parser("client", help="Chạy ở chế độ Client (người tham gia)")
    client_parser.add_argument("--ip", type=str, help="Địa chỉ IP ZeroTier của máy Host")
    client_parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Cổng TCP của Host (mặc định: {DEFAULT_PORT})")
    client_parser.add_argument("--name", type=str, help="Tên của bạn khi vào phòng")

    args = parser.parse_args()

    # Nếu người dùng chạy trực tiếp `python aoe_helper.py` không kèm cờ lệnh,
    # chương trình sẽ tự động hiển thị menu tương tác thân thiện.
    if not args.mode:
        print("\n" + "=" * 55)
        print("    CHƯƠNG TRÌNH HỖ TRỢ CHƠI AOE 1 QUA ZEROTIER")
        print("=" * 55)
        print("1. Chế độ Host   (Máy chủ tạo phòng)")
        print("2. Chế độ Client (Máy khách kết nối vào phòng)")
        choice = input("Vui lòng chọn chế độ (1 hoặc 2): ").strip()

        if choice == "1":
            name = input("Nhập tên hiển thị của bạn [Chủ Phòng]: ").strip() or "Chủ Phòng"
            port_input = input(f"Nhập cổng TCP [mặc định {DEFAULT_PORT}]: ").strip()
            port = int(port_input) if port_input.isdigit() else DEFAULT_PORT
            server = AoEHost(port=port, host_name=name)
            server.start()

        elif choice == "2":
            host_ip = input("Nhập địa chỉ IP ZeroTier của máy Host: ").strip()
            while not host_ip:
                host_ip = input("IP Host không được để trống, vui lòng nhập lại: ").strip()

            name = input("Nhập tên của bạn [Khách]: ").strip() or "Khách"
            port_input = input(f"Nhập cổng TCP [mặc định {DEFAULT_PORT}]: ").strip()
            port = int(port_input) if port_input.isdigit() else DEFAULT_PORT
            
            client = AoEClient(host_ip=host_ip, port=port, player_name=name)
            client.start()
        else:
            print("Lựa chọn không hợp lệ. Thoát chương trình.")
            sys.exit(1)

    elif args.mode == "host":
        server = AoEHost(port=args.port, host_name=args.name)
        server.start()

    elif args.mode == "client":
        if not args.ip:
            args.ip = input("Nhập IP ZeroTier của máy Host: ").strip()
        if not args.name:
            args.name = input("Nhập tên hiển thị của bạn: ").strip() or "Khách"

        client = AoEClient(host_ip=args.ip, port=args.port, player_name=args.name)
        client.start()


if __name__ == "__main__":
    main()
