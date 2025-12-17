import socket
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
import os
import base64
from chat_protocol import send_packet, recv_packet


class ChatClientGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Python 超级聊天室 (Pro版)')
        self.geometry('800x600')
        self.protocol('WM_DELETE_WINDOW', self.on_close)

        # 确保下载目录
        self.download_dir = "downloads"
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

        self.sock = None
        self.running = False
        self.default_host = '127.0.0.1'
        self.default_port = 3000

        self.create_widgets()

    def create_widgets(self):
        # --- 顶部设置区 ---
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=10, pady=10)

        ttk.Label(top, text="昵称:").pack(side=tk.LEFT)
        self.name_var = tk.StringVar(value='User')
        ttk.Entry(top, width=10, textvariable=self.name_var).pack(side=tk.LEFT, padx=5)

        ttk.Label(top, text="IP:").pack(side=tk.LEFT)
        self.host_var = tk.StringVar(value=self.default_host)
        ttk.Entry(top, width=12, textvariable=self.host_var).pack(side=tk.LEFT, padx=5)

        ttk.Label(top, text="端口:").pack(side=tk.LEFT)
        self.port_var = tk.IntVar(value=self.default_port)
        ttk.Entry(top, width=6, textvariable=self.port_var).pack(side=tk.LEFT, padx=5)

        self.connect_btn = ttk.Button(top, text="连接服务器", command=self.toggle_connection)
        self.connect_btn.pack(side=tk.LEFT, padx=10)

        # --- 聊天显示区 (核心升级部分) ---
        self.chat_area = scrolledtext.ScrolledText(self, state=tk.DISABLED, font=("Microsoft YaHei UI", 10))
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 定义样式标签 (Tag)
        # 1. 元数据行：时间
        self.chat_area.tag_config('time', foreground='gray', font=("Arial", 8))
        # 2. 类型标识
        self.chat_area.tag_config('type_text', foreground='#2196F3', font=("Arial", 9, "bold"))  # 蓝色
        self.chat_area.tag_config('type_file', foreground='#FF9800', font=("Arial", 9, "bold"))  # 橙色
        # 3. 用户名
        self.chat_area.tag_config('name_me', foreground='#4CAF50', font=("Microsoft YaHei UI", 9, "bold"))  # 绿色
        self.chat_area.tag_config('name_other', foreground='#3F51B5', font=("Microsoft YaHei UI", 9, "bold"))  # 深蓝
        self.chat_area.tag_config('name_sys', foreground='gray', font=("Microsoft YaHei UI", 9, "bold"))
        # 4. 内容正文
        self.chat_area.tag_config('content', lmargin1=20, lmargin2=20)  # 缩进

        # --- 底部输入区 ---
        bottom = ttk.Frame(self)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

        self.file_btn = ttk.Button(bottom, text="📄 发文件", width=10, command=self.select_and_send_file)
        self.file_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.msg_var = tk.StringVar()
        self.entry = ttk.Entry(bottom, textvariable=self.msg_var)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.entry.bind('<Return>', lambda e: self.send_text_thread())

        self.send_btn = ttk.Button(bottom, text="发送消息", command=self.send_text_thread)
        self.send_btn.pack(side=tk.RIGHT)

        self.set_ui_state(False)

    def set_ui_state(self, connected):
        state = '!disabled' if connected else 'disabled'
        self.connect_btn.config(text="断开连接" if connected else "连接服务器")
        self.entry.state([state])
        self.send_btn.state([state])
        self.file_btn.state([state])

    def toggle_connection(self):
        if self.running:
            self.disconnect()
        else:
            threading.Thread(target=self.connect, daemon=True).start()

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host_var.get(), self.port_var.get()))
            self.running = True
            self.after(0, self.set_ui_state, True)
            self.after(0, self.append_msg, '系统', '已成功连接到服务器', 'text', True)
            threading.Thread(target=self.receiver_loop, daemon=True).start()
        except Exception as e:
            self.running = False
            self.after(0, messagebox.showerror, "连接失败", str(e))

    def disconnect(self):
        self.running = False
        if self.sock:
            self.sock.close()
            self.sock = None
        self.set_ui_state(False)
        self.append_msg('系统', '已断开连接', 'text', True)

    def receiver_loop(self):
        while self.running and self.sock:
            data = recv_packet(self.sock)
            if not data: break

            msg_type = data.get('type')
            sender = data.get('from', 'Unknown')

            if msg_type == 'text':
                self.after(0, self.append_msg, sender, data.get('msg'), 'text', False)
            elif msg_type == 'file':
                filename = data.get('filename')
                self.save_file(sender, filename, data.get('data'))

        if self.running:
            self.after(0, self.disconnect)
            self.after(0, self.append_msg, '系统', '服务器已关闭', 'text', True)

    def save_file(self, sender, filename, b64_data):
        try:
            save_path = os.path.join(self.download_dir, filename)
            base, ext = os.path.splitext(save_path)
            counter = 1
            while os.path.exists(save_path):
                save_path = f"{base}_{counter}{ext}"
                counter += 1

            with open(save_path, 'wb') as f:
                f.write(base64.b64decode(b64_data))

            msg = f"接收到文件: {os.path.basename(save_path)}\n文件已保存至: {save_path}"
            self.after(0, self.append_msg, sender, msg, 'file', False)
        except Exception as e:
            self.after(0, self.append_msg, '系统', f"接收文件失败: {e}", 'text', True)

    def send_text_thread(self):
        msg = self.msg_var.get().strip()
        if msg:
            threading.Thread(target=self._send_logic, args=('text', msg), daemon=True).start()
            self.msg_var.set('')

    def select_and_send_file(self):
        filepath = filedialog.askopenfilename()
        if filepath:
            if os.path.getsize(filepath) > 10 * 1024 * 1024:  # 10MB Limit
                messagebox.showwarning("提示", "文件过大，建议发送 10MB 以下文件")
                return
            threading.Thread(target=self._send_file_logic, args=(filepath,), daemon=True).start()

    def _send_file_logic(self, filepath):
        try:
            filename = os.path.basename(filepath)
            self.after(0, self.append_msg, "我", f"正在发送文件: {filename}...", 'text', True)  # 临时提示

            with open(filepath, 'rb') as f:
                b64_str = base64.b64encode(f.read()).decode('utf-8')

            packet = {"type": "file", "from": self.name_var.get(), "filename": filename, "data": b64_str}

            if send_packet(self.sock, packet):
                # 发送成功后显示
                self.after(0, self.append_msg, "我", f"文件 {filename} 发送成功", 'file', True)
            else:
                self.after(0, self.append_msg, "系统", "发送失败", 'text', True)
        except Exception as e:
            self.after(0, self.append_msg, "系统", f"文件错误: {e}", 'text', True)

    def _send_logic(self, msg_type, content):
        packet = {"type": msg_type, "from": self.name_var.get()}
        if msg_type == 'text': packet['msg'] = content

        if send_packet(self.sock, packet):
            if msg_type == 'text':
                self.after(0, self.append_msg, "我", content, 'text', True)
        else:
            self.after(0, self.disconnect)

    def append_msg(self, sender, text, msg_type, is_me_or_sys):
        """
        核心 UI 更新函数
        sender: 发送者名字
        text: 内容
        msg_type: 'text' | 'file'
        is_me_or_sys: True (我/系统) | False (别人) -> 用于决定名字颜色
        """
        self.chat_area.config(state=tk.NORMAL)

        # 1. 准备数据
        ts = datetime.now().strftime('%H:%M:%S')

        # 2. 决定标签颜色
        if sender == '系统':
            name_tag = 'name_sys'
        elif sender == '我':
            name_tag = 'name_me'
        else:
            name_tag = 'name_other'

        type_str = "[文本]" if msg_type == 'text' else "[文件]"
        type_tag = 'type_text' if msg_type == 'text' else 'type_file'

        # 3. 插入第一行：[时间] [类型] 用户名
        self.chat_area.insert(tk.END, f"[{ts}] ", 'time')
        self.chat_area.insert(tk.END, f"{type_str} ", type_tag)
        self.chat_area.insert(tk.END, f"{sender}:\n", name_tag)

        # 4. 插入第二行：内容 (带缩进)
        self.chat_area.insert(tk.END, f"{text}\n\n", 'content')

        self.chat_area.config(state=tk.DISABLED)
        self.chat_area.see(tk.END)

    def on_close(self):
        self.disconnect()
        self.destroy()


if __name__ == '__main__':
    app = ChatClientGUI()
    app.mainloop()