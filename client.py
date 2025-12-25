import socket
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
import json
import struct
import os
import base64
from chat_protocol import send_packet, recv_packet


class ChatClientGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Python 超级聊天室 (Pro Max - 私聊版)')
        self.geometry('900x700')
        self.protocol('WM_DELETE_WINDOW', self.on_close)

        self.download_dir = "downloads"
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)

        self.sock = None
        self.running = False
        self.default_host = '127.0.0.1'
        self.default_port = 3000

        # 线程安全数据
        self.available_files = {}

        self.create_widgets()

    def create_widgets(self):
        # --- 顶部连接区 ---
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

        # --- 聊天显示区 ---
        self.chat_area = scrolledtext.ScrolledText(self, state=tk.DISABLED, font=("Microsoft YaHei UI", 10))
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        # 样式标签
        self.chat_area.tag_config('time', foreground='gray', font=("Arial", 8))
        self.chat_area.tag_config('type_text', foreground='#2196F3', font=("Arial", 9, "bold"))  # 蓝色
        self.chat_area.tag_config('type_private', foreground='#E91E63', font=("Arial", 9, "bold"))  # 粉色 (私聊)
        self.chat_area.tag_config('type_file', foreground='#FF9800', font=("Arial", 9, "bold"))  # 橙色

        self.chat_area.tag_config('name_me', foreground='#4CAF50', font=("Microsoft YaHei UI", 9, "bold"))
        self.chat_area.tag_config('name_other', foreground='#3F51B5', font=("Microsoft YaHei UI", 9, "bold"))
        self.chat_area.tag_config('name_sys', foreground='gray', font=("Microsoft YaHei UI", 9, "bold"))
        self.chat_area.tag_config('content', lmargin1=20, lmargin2=20)

        # --- 底部操作区 ---
        bottom = ttk.Frame(self)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

        # 1. 文件操作
        f_frame = ttk.LabelFrame(bottom, text="文件操作")
        f_frame.pack(side=tk.LEFT, padx=5, fill=tk.Y)

        self.file_btn = ttk.Button(f_frame, text="📤 上传", width=8, command=self.select_and_send_file)
        self.file_btn.pack(side=tk.LEFT, padx=5, pady=5)

        self.file_combo = ttk.Combobox(f_frame, width=20, state="readonly")
        self.file_combo.pack(side=tk.LEFT, padx=5, pady=5)

        self.download_btn = ttk.Button(f_frame, text="📥 下载", width=8, command=self.request_download, state='disabled')
        self.download_btn.pack(side=tk.LEFT, padx=5, pady=5)

        # 2. 消息发送
        m_frame = ttk.LabelFrame(bottom, text="发送消息")
        m_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5)

        # 私聊选择框
        ttk.Label(m_frame, text="发送给:").pack(side=tk.LEFT, padx=5)
        self.target_combo = ttk.Combobox(m_frame, width=12, state="readonly")
        self.target_combo.set("所有人")
        self.target_combo['values'] = ["所有人"]
        self.target_combo.pack(side=tk.LEFT, padx=5)

        self.msg_var = tk.StringVar()
        self.entry = ttk.Entry(m_frame, textvariable=self.msg_var)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
        self.entry.bind('<Return>', lambda e: self.send_text_thread())

        self.send_btn = ttk.Button(m_frame, text="发送", command=self.send_text_thread)
        self.send_btn.pack(side=tk.RIGHT, padx=5, pady=5)

        self.set_ui_state(False)

    def set_ui_state(self, connected):
        state = '!disabled' if connected else 'disabled'
        self.connect_btn.config(text="断开连接" if connected else "连接服务器")
        self.entry.state([state])
        self.send_btn.state([state])
        self.file_btn.state([state])
        self.target_combo.state([state])
        if not connected:
            self.file_combo['values'] = []
            self.download_btn.state(['disabled'])
            self.target_combo['values'] = ["所有人"]
            self.target_combo.set("所有人")

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
            self.after(0, self.append_msg, '系统', '已成功连接到服务器', 'text', '所有人', True)
            threading.Thread(target=self.receiver_loop, daemon=True).start()
            # 启动心跳线程，保持与服务端的活跃状态
            self.start_heartbeat()
        except Exception as e:
            self.running = False
            self.after(0, messagebox.showerror, "连接失败", str(e))

    def disconnect(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
        self.set_ui_state(False)
        self.append_msg('系统', '已断开连接', 'text', '所有人', True)

    # ==================== 接收线程 ====================
    def receiver_loop(self):
        disconnect_reason = None
        while self.running and self.sock:
            try:
                data = recv_packet(self.sock)
            except (json.JSONDecodeError, struct.error) as e:
                disconnect_reason = f"协议错误，连接已断开: {e}"
                break
            except OSError:
                disconnect_reason = "网络错误，连接已断开"
                break
            except Exception as e:
                disconnect_reason = f"接收错误，连接已断开: {e}"
                break

            if not data:
                break

            msg_type = data.get('type')
            sender = data.get('from', 'Unknown')

            if msg_type == 'text':
                target = data.get('target', '所有人')
                msg = data.get('msg')
                # 区分是别人发给我的私聊，还是我发给别人的私聊确认
                is_me_or_sys = (sender == '系统' or sender == self.name_var.get())
                self.after(0, self.append_msg, sender, msg, 'text', target, is_me_or_sys)

            elif msg_type == 'user_list':
                users = data.get('users', [])
                self.after(0, self.handle_user_list, users)

            elif msg_type == 'file_notify':
                file_id, filename = data.get('file_id'), data.get('filename')
                self.after(0, self.handle_file_notify, file_id, filename, sender)

            elif msg_type == 'file_response':
                file_id, filename, b64_data = data.get('file_id'), data.get('filename'), data.get('data')
                self.after(0, self.handle_file_response, file_id, filename, b64_data)

        if self.running:
            self.after(0, self.disconnect)
            if disconnect_reason:
                self.after(0, self.append_msg, '系统', disconnect_reason, 'text', '所有人', True)
            else:
                self.after(0, self.append_msg, '系统', '服务器已关闭', 'text', '所有人', True)

    # ==================== 主线程处理函数 ====================
    def handle_user_list(self, users):
        """更新在线用户下拉框"""
        current_selection = self.target_combo.get()
        my_name = self.name_var.get()

        # 列表逻辑：所有人 + 其他用户 (排除自己)
        display_users = ["所有人"] + [u for u in users if u != my_name]

        self.target_combo['values'] = display_users

        # 如果当前选中的人还在列表里，保持选中；否则重置为所有人
        if current_selection in display_users:
            self.target_combo.set(current_selection)
        else:
            self.target_combo.current(0)

    def handle_file_notify(self, file_id, filename, sender):
        self.available_files[file_id] = {"filename": filename, "from": sender}
        msg = f"上传了文件：{filename}\n（可在左侧选择下载）"
        self.append_msg(sender, msg, 'file', '所有人', False)
        self.update_file_list_ui()

    def handle_file_response(self, file_id, filename, b64_data):
        if file_id in self.available_files:
            del self.available_files[file_id]
            self.update_file_list_ui()
        self.save_file("服务器", filename, b64_data)

    def update_file_list_ui(self):
        items = [f"{info['filename']} (来自 {info['from']})" for info in self.available_files.values()]
        self.file_combo['values'] = items
        if items:
            self.file_combo.current(0)
            self.download_btn.state(['!disabled'])
        else:
            self.download_btn.state(['disabled'])

    # ==================== 发送逻辑 ====================
    def send_text_thread(self):
        msg = self.msg_var.get().strip()
        target = self.target_combo.get()
        if msg:
            threading.Thread(target=self._send_logic, args=('text', msg, target), daemon=True).start()
            self.msg_var.set('')

    def _send_logic(self, msg_type, content, target='所有人'):
        packet = {"type": msg_type, "from": self.name_var.get(), "target": target}
        if msg_type == 'text': packet['msg'] = content
        try:
            send_packet(self.sock, packet)
        except Exception:
            # 发送失败由 disconnect/receiver 处理
            self.after(0, self.disconnect)

    def select_and_send_file(self):
        filepath = filedialog.askopenfilename()
        if filepath:
            threading.Thread(target=self._send_file_logic, args=(filepath,), daemon=True).start()

    def _send_file_logic(self, filepath):
        """分块上传文件，避免大文件一次性加载到内存"""
        try:
            filename = os.path.basename(filepath)
            file_size = os.path.getsize(filepath)
            
            # 检查文件大小
            MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
            if file_size > MAX_FILE_SIZE:
                self.after(0, self.append_msg, "系统", 
                          f"文件过大 ({file_size/1024/1024:.1f}MB)，最大允许 10MB", 
                          'text', '所有人', True)
                return
            
            self.after(0, self.append_msg, "我", 
                      f"正在上传文件: {filename} ({file_size/1024:.1f}KB)...", 
                      'text', '所有人', True)
            
            # 分块读取并编码（每块 1MB）
            CHUNK_SIZE = 1024 * 1024  # 1MB
            chunks = []
            
            with open(filepath, 'rb') as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    # 分块进行 Base64 编码
                    chunks.append(base64.b64encode(chunk).decode('utf-8'))
            
            # 合并所有块
            b64_str = ''.join(chunks)
            
            packet = {
                "type": "file_upload", 
                "from": self.name_var.get(), 
                "filename": filename, 
                "data": b64_str,
                "size": file_size
            }
            
            try:
                send_packet(self.sock, packet)
                self.after(0, self.append_msg, "系统", 
                          f"文件上传完成: {filename}", 'text', '所有人', True)
            except Exception as e:
                self.after(0, self.append_msg, "系统", f"上传失败: {e}", 'text', '所有人', True)
                self.after(0, self.disconnect)
                return
        except Exception as e:
            self.after(0, self.append_msg, "系统", f"上传错误: {e}", 'text', '所有人', True)

    def request_download(self):
        selected = self.file_combo.get()
        if not selected: return
        target_id = None
        for fid, info in self.available_files.items():
            if f"{info['filename']} (来自 {info['from']})" == selected:
                target_id = fid
                break
        if target_id:
            try:
                send_packet(self.sock, {"type": "file_request", "file_id": target_id})
                self.after(0, self.append_msg, "我", f"请求下载: {self.available_files[target_id]['filename']}", 'text', '所有人', True)
                self.after(0, self.download_btn.state, ['disabled'])
            except Exception as e:
                self.after(0, self.append_msg, "系统", f"请求下载失败: {e}", 'text', '所有人', True)
                self.after(0, self.disconnect)

    def start_heartbeat(self, interval=25):
        """后台心跳线程，定期发送心跳包到服务器，支持指数退避重连。"""
        def loop():
            consecutive_failures = 0
            max_failures = 5  # 最大连续失败次数
            base_backoff = 2  # 基础退避时间（秒）
            max_backoff = 60  # 最大退避时间（秒）
            
            while self.running and self.sock:
                try:
                    send_packet(self.sock, {"type": "heartbeat", "from": self.name_var.get()})
                    consecutive_failures = 0  # 成功后重置失败计数
                    time.sleep(interval)
                except Exception as e:
                    consecutive_failures += 1
                    
                    # 计算指数退避时间
                    backoff_time = min(base_backoff * (2 ** (consecutive_failures - 1)), max_backoff)
                    
                    if consecutive_failures >= max_failures:
                        # 达到最大失败次数，触发断开
                        try:
                            self.after(0, self.append_msg, '系统', 
                                     f'心跳发送失败 {consecutive_failures} 次，连接已断开', 
                                     'text', '所有人', True)
                            self.after(0, self.disconnect)
                        except:
                            pass
                        break
                    else:
                        # 指数退避后重试
                        try:
                            self.after(0, self.append_msg, '系统', 
                                     f'心跳发送失败，{backoff_time}秒后重试 ({consecutive_failures}/{max_failures})', 
                                     'text', '所有人', True)
                        except:
                            pass
                        time.sleep(backoff_time)
                        
        threading.Thread(target=loop, daemon=True).start()

    def save_file(self, sender, filename, b64_data):
        """分块解码并保存文件，避免大文件内存溢出"""
        try:
            # 安全修复：防止路径遍历攻击
            filename = os.path.basename(filename)  # 移除路径部分
            # 过滤危险字符，只保留安全字符
            filename = "".join(c for c in filename if c.isalnum() or c in '._- ')
            filename = filename.strip()  # 去除首尾空白
            if not filename:
                filename = "downloaded_file"
            
            save_path = os.path.join(self.download_dir, filename)
            base, ext = os.path.splitext(save_path)
            counter = 1
            while os.path.exists(save_path):
                save_path = f"{base}_{counter}{ext}"
                counter += 1
            
            # 分块解码并写入（每块处理 4MB 的 Base64 数据）
            CHUNK_SIZE = 4 * 1024 * 1024  # 4MB Base64 数据
            total_size = len(b64_data)
            
            with open(save_path, 'wb') as f:
                for i in range(0, total_size, CHUNK_SIZE):
                    chunk = b64_data[i:i + CHUNK_SIZE]
                    decoded_chunk = base64.b64decode(chunk)
                    f.write(decoded_chunk)
            
            file_size = os.path.getsize(save_path)
            msg = f"文件下载完成: {os.path.basename(save_path)} ({file_size/1024:.1f}KB)\n保存路径: {save_path}"
            self.append_msg(sender, msg, 'file', '所有人', False)
            self.update_file_list_ui()
        except Exception as e:
            self.append_msg('系统', f"保存文件失败: {e}", 'text', '所有人', True)

    # ==================== UI 显示 ====================
    def append_msg(self, sender, text, msg_type, target, is_me_or_sys):
        self.chat_area.config(state=tk.NORMAL)
        ts = datetime.now().strftime('%H:%M:%S')

        # 标签逻辑
        if sender == '系统':
            name_tag = 'name_sys'
        elif is_me_or_sys:
            name_tag = 'name_me'
        else:
            name_tag = 'name_other'

        # 消息类型标签
        if msg_type == 'file':
            type_str = "[文件]"
            type_tag = 'type_file'
        elif target != '所有人':
            type_str = "[私聊]"
            type_tag = 'type_private'  # 粉色高亮
        else:
            type_str = "[文本]"
            type_tag = 'type_text'

        # 显示格式：[时间] [类型] User (-> Target): 内容
        self.chat_area.insert(tk.END, f"[{ts}] ", 'time')
        self.chat_area.insert(tk.END, f"{type_str} ", type_tag)
        self.chat_area.insert(tk.END, f"{sender}", name_tag)

        if target != '所有人':
            self.chat_area.insert(tk.END, f" -> {target}", type_tag)

        self.chat_area.insert(tk.END, ":\n", name_tag)
        self.chat_area.insert(tk.END, f"{text}\n\n", 'content')

        self.chat_area.config(state=tk.DISABLED)
        self.chat_area.see(tk.END)

    def on_close(self):
        self.disconnect()
        self.destroy()


if __name__ == '__main__':
    app = ChatClientGUI()
    app.mainloop()
