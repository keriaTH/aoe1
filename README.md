# ⚔️ HỆ THỐNG HỖ TRỢ CHƠI AGE OF EMPIRES 1 QUA ZEROTIER

> **Dự án**: Công cụ tự động hóa kết nối, kiểm tra mạng, chat nhóm và đồ họa HD cho nhóm 3–6 người chơi Đế Chế 1 (Bản cổ điển The Rise of Rome) qua mạng ảo ZeroTier.

---

## 📌 1. TỔNG QUAN CÁC FILE ĐÃ TẠO & CẤU HÌNH

| Tên File | Vai Trò & Chức Năng |
| :--- | :--- |
| **`aoe_gui.py`** | **Ứng dụng giao diện đồ họa chính (PyQt6)**: Giao diện Dark Gaming cao cấp, tự động quét tìm phòng qua ZeroTier, kiểm tra TCP, đo ping thời gian thực, chat nhóm, đồng bộ Ready/Start và tự động mở game. |
| **`aoe_helper.py`** | **Ứng dụng dòng lệnh (CLI)**: Chỉ dùng 100% thư viện chuẩn của Python (`socket`, `threading`, `time`, `argparse`). Chạy được ngay trên mọi máy tính có Python mà không cần cài thêm bất kỳ thư viện nào. |
| **`game-de-che-1/hook.ini`** | **Cấu hình đồ họa Full HD**: Tùy chỉnh độ phân giải 1920x1080, chế độ Cửa Sổ không viền (Windowed), bật hiển thị khung hình (`ShowFps=1`) và sửa đường dẫn tương thích mọi máy. |
| **`game-de-che-1/`** | **Thư mục game Đế Chế 1 đầy đủ**: Đã được kiểm tra 100% toàn vẹn (`Empiresx.exe`, data 16 nền văn minh, 84 file âm thanh & taunt, DirectPlay, patch fix màu). |

---

## 🚀 2. CHI TIẾT CÁC TÍNH NĂNG ĐÃ TRIỂN KHAI

### 1. Tự Động Tìm Phòng (Auto-Discovery qua ZeroTier)
* **Cơ chế**: Host phát tín hiệu UDP Broadcast (Beacon) ngầm qua mạng ảo ZeroTier mỗi 1.5 giây.
* **Trải nghiệm**: Máy Khách (Client) vừa mở ứng dụng lên là **tự động thấy phòng của Host sau 1 giây**.
* 👉 **Không ai phải copy hay gõ bất kỳ con số IP nào! Bấm 1-Click là vào phòng.**

### 2. Đồng Bộ Sẵn Sàng (Ready) & Khởi Động Đồng Loạt (Start Game)
* **Khách bấm "⚡ SẴN SÀNG"**:
  * Trạng thái trên máy Host lập tức đổi sang `🟢 ĐÃ SẴN SÀNG`.
  * Bộ đếm trên Host cập nhật số người đã sẵn sàng (VD: `Sẵn sàng: 2 / 2 người`).
* **Host bấm "🚀 BẮT ĐẦU TRẬN ĐẤU"**:
  * **Cả 2 máy tự động mở game `Empiresx.exe` đồng thời!**
  * Tự động bỏ qua đoạn video giới thiệu mở đầu dài dòng nhờ cờ `nostartup`.

### 3. Tự Động Nạp Sẵn IP Vào Game (DirectPlay Registry)
* Phần mềm tự động nạp thẳng địa chỉ IP của Host vào **Windows Registry DirectPlay** (`Software\Microsoft\DirectPlay\...`) và Clipboard.
* Khi game mở lên, ô IP trong mục `Internet TCP/IP` đã **được điền sẵn chính xác địa chỉ của Host**.

### 4. Đồ Họa Cửa Sổ Full HD 1080p & Hiện FPS
* Tích hợp tùy chọn `[x] 🪟 Cửa Sổ HD 1080p (Hiện FPS)` ngay trên giao diện.
* Mở game qua bộ công cụ cửa sổ hóa kết hợp `hook.ini`:
  * Màn hình chuẩn Full HD 1920x1080 không bị méo hình.
  * Hiển thị số khung hình **FPS** thời gian thực ở góc màn hình.

### 5. Kiểm Tra Kết Nối, Đo Ping & Chat Nhóm
* **Đo Ping thời gian thực**: Nút đo Ping và tùy chọn tự động đo mỗi 3 giây, mã màu trực quan:
  * 🟢 **Xanh**: `< 60 ms` (Mượt mà).
  * 🟡 **Vàng**: `60 - 130 ms` (Bình thường).
  * 🔴 **Đỏ**: `> 130 ms` (Cảnh báo lag).
* **Phòng Chat**: Chat chung real-time giữa Host và các Client, có các phím tắt chat nhanh (*"Ready!"*, *"Vào game thôi!"*, *"Chờ 1 phút"*...).

---

## 🎮 3. QUY TRÌNH CHƠI ĐẾ CHẾ (DÀNH CHO BẠN BÈ)

### Bước 1: Chuẩn bị mạng
* Cả nhóm mở ZeroTier và Join vào cùng một Network ID (trạng thái báo **OK**).

### Bước 2: Mở công cụ hỗ trợ
* Chạy ứng dụng giao diện:
  ```powershell
  python aoe_gui.py
  ```
* **Máy Chủ (Host)**: Bấm **`🚀 Khởi Động Server Host`**.
* **Máy Khách (Client)**: Thấy phòng Host hiện lên -> Bấm **`⚡ VÀO PHÒNG NGAY`** -> Bấm **`⚡ SẴN SÀNG`**.
* **Máy Chủ (Host)**: Thấy các bạn đã Ready -> Bấm **`🚀 BẮT ĐẦU TRẬN ĐẤU`**.

### Bước 3: Vào phòng trong Game (Cả 2 máy tự mở game)
1. Trong menu chính của game, click chuột vào **`Multiplayer`**.
2. Ô *Connection Type* chọn **`Internet TCP/IP Connection For DirectPlay`**.
3. **Host**: Bấm **`Create`** (Tạo phòng).
4. **Client**: Bấm **`Show Games`** *(IP đã tự nạp sẵn, chỉ việc bấm OK)* -> Chọn phòng bấm **`Join`**!
