import socket
import threading
import time
import json
import logging
import hashlib
import uuid
import os
import shutil
import base64
from datetime import datetime
from logging.handlers import RotatingFileHandler
from chat_protocol import send_packet, recv_packet

# === 全局配置与数据 ===
config = {}
banned_ips = set()
muted_ips = set()
global_mute = False
server_running = True
admin_authenticated = False

HOST = '0.0.0.0'
PORT = 3000

# sock -> {"addr": addr, "name": str, "last_heartbeat": float}
clients_manager = {}
name_to_socket = {}  # 反向索引：name -> socket (优化私聊查找)

TEMP_FILES_DIR = "server_temp_files"
if not os.path.exists(TEMP_FILES_DIR):
    os.makedirs(TEMP_FILES_DIR)

uploaded_files = {}  # file_id -> info
FILE_EXPIRE_SECONDS = 24 * 3600
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {'.txt', '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.zip', '.rar', '.doc', '.docx', '.xls', '.xlsx'}

data_lock = threading.Lock()
logger = None
last_cleanup_time = 0


# ====================== 配置与日志 (保持不变) ======================
def load_config():
    global config, HOST, PORT, FILE_EXPIRE_SECONDS
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        HOST = config['server']['host']
        PORT = config['server']['port']
        if 'file_expire_hours' in config.get('security', {}):
            FILE_EXPIRE_SECONDS = config['security']['file_expire_hours'] * 3600
        return True
    except FileNotFoundError:
        print("警告: config.json 未找到，使用默认配置")
        config = {
            "server": {"host": "0.0.0.0", "port": 3000, "max_connections": 50},
            "admin": {"password": "admin123", "password_enabled": True},
            "security": {
                "enable_message_filter": True, "max_message_length": 1000,
                "heartbeat_interval": 30, "heartbeat_timeout": 90,
                "file_expire_hours": 24
            },
            "logging": {"level": "INFO", "file": "server.log", "max_bytes": 10485760, "backup_count": 5},
            "data": {"banned_ips_file": "banned_ips.json", "muted_ips_file": "muted_ips.json"}
        }
        return False
    except Exception as e:
        print(f"配置文件加载失败: {e}")
        return False


def setup_logging():
    global logger
    logger = logging.getLogger('ChatServer')
    logger.setLevel(getattr(logging, config['logging']['level']))
    file_handler = RotatingFileHandler(
        config['logging']['file'], maxBytes=config['logging']['max_bytes'],
        backupCount=config['logging']['backup_count'], encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def load_persistent_data():
    global banned_ips, muted_ips
    try:
        with open(config['data']['banned_ips_file'], 'r') as f:
            banned_ips = set(json.load(f))
        logger.info(f"已加载 {len(banned_ips)} 个封禁IP")
    except FileNotFoundError:
        logger.info("未找到封禁列表文件，从空列表开始")
    except json.JSONDecodeError as e:
        logger.error(f"封禁列表格式错误: {e}")
    except Exception as e:
        logger.error(f"加载封禁列表失败: {e}")

    try:
        with open(config['data']['muted_ips_file'], 'r') as f:
            muted_ips = set(json.load(f))
        logger.info(f"已加载 {len(muted_ips)} 个禁言IP")
    except FileNotFoundError:
        logger.info("未找到禁言列表文件，从空列表开始")
    except json.JSONDecodeError as e:
        logger.error(f"禁言列表格式错误: {e}")
    except Exception as e:
        logger.error(f"加载禁言列表失败: {e}")


def save_persistent_data():
    try:
        with open(config['data']['banned_ips_file'], 'w') as f:
            json.dump(list(banned_ips), f)
        with open(config['data']['muted_ips_file'], 'w') as f:
            json.dump(list(muted_ips), f)
        logger.info("数据已保存")
    except Exception as e:
        logger.error(f"保存数据失败: {e}")


def verify_admin_password(password):
    """验证管理员密码"""
    if not config['admin']['password_enabled']:
        return True
    expected = config['admin']['password']
    return hashlib.sha256(password.encode()).hexdigest() == hashlib.sha256(expected.encode()).hexdigest()


def validate_filename(filename):
    """验证并清理文件名"""
    # 移除路径，只保留文件名
    filename = os.path.basename(filename)
    # 移除危险字符
    filename = filename.replace('..', '').replace('/', '').replace('\\', '')
    return filename


def validate_file_extension(filename):
    """验证文件扩展名"""
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


# ====================== 辅助函数 ======================
class Color:
    HEADER = '\033[95m';
    BLUE = '\033[94m';
    CYAN = '\033[96m';
    GREEN = '\033[92m'
    WARNING = '\033[93m';
    FAIL = '\033[91m';
    BOLD = '\033[1m';
    GREY = '\033[90m';
    ENDC = '\033[0m'


def get_time(): return datetime.now().strftime('%H:%M:%S')


def log_system(prefix, message, color=Color.ENDC):
    print(f"{Color.GREY}[{get_time()}]{Color.ENDC} {color}{Color.BOLD}[{prefix}]{Color.ENDC} {message}")
    if logger: logger.info(f"[{prefix}] {message}")


def log_message(name, msg, msg_type='text', target='所有人'):
    ts = f"{Color.GREY}{get_time()}{Color.ENDC}"
    name_display = f"{Color.CYAN}{name}{Color.ENDC}"
    target_display = "" if target == '所有人' else f" {Color.FAIL}-> {target}{Color.ENDC}"

    if msg_type == 'text':
        print(f"{ts} {name_display}{target_display} {Color.GREY}>>{Color.ENDC} {msg}")
        if logger: logger.info(f"{name} -> {target} >> {msg}")
    elif msg_type == 'file':
        print(f"{ts} {name_display} {Color.GREY}>>{Color.ENDC} {Color.WARNING}[文件] {msg}{Color.ENDC}")
        if logger: logger.info(f"{name} >> [文件] {msg}")


def broadcast(packet, exclude_sock=None):
    with data_lock:
        dead_sockets = []
        for sock in list(clients_manager.keys()):
            if sock is exclude_sock: continue
            try:
                send_packet(sock, packet)
            except:
                dead_sockets.append(sock)
        for sock in dead_sockets:
            del clients_manager[sock]


def broadcast_user_list():
    """向所有客户端推送当前在线用户列表"""
    with data_lock:
        # 过滤掉初始连接还没发过包的 "未命名" 用户
        users = [info['name'] for info in clients_manager.values() if info['name'] != "未命名"]

    # 对列表去重并排序，为了美观
    users = sorted(list(set(users)))
    packet = {"type": "user_list", "users": users}
    broadcast(packet, None)  # 发给所有人


def cleanup_expired_files():
    global uploaded_files
    now = time.time()
    with data_lock:
        expired = [fid for fid, info in uploaded_files.items() if now - info['upload_time'] > FILE_EXPIRE_SECONDS]
        for fid in expired:
            path = uploaded_files[fid]['path']
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass
            del uploaded_files[fid]
            logger.info(f"清理过期文件 ID: {fid[:8]}")


def heartbeat_monitor():
    global last_cleanup_time
    while server_running:
        time.sleep(10)
        now = time.time()
        timeout = config['security']['heartbeat_timeout']

        need_update_list = False
        with data_lock:
            dead_sockets = [sock for sock, info in clients_manager.items() if now - info["last_heartbeat"] > timeout]
            for sock in dead_sockets:
                name = clients_manager[sock]['name']
                addr = clients_manager[sock]['addr'][0]
                logger.warning(f"心跳超时: {addr} ({name})")
                try:
                    sock.close()
                except Exception as e:
                    logger.error(f"关闭超时连接时出错: {e}")
                # 清理反向索引
                if name in name_to_socket and name_to_socket[name] == sock:
                    del name_to_socket[name]
                del clients_manager[sock]
                need_update_list = True

        if need_update_list:
            broadcast_user_list()

        # 每小时清理一次过期文件
        if now - last_cleanup_time > 3600:
            cleanup_expired_files()
            last_cleanup_time = now


# ====================== 核心逻辑 ======================
def handle_client(client_socket, addr):
    global clients_manager
    with data_lock:
        clients_manager[client_socket] = {"addr": addr, "name": "未命名", "last_heartbeat": time.time()}

    log_system("连接", f"{addr[0]} 已加入", Color.GREEN)

    try:
        try:
            send_packet(client_socket, {"type": "text", "from": "系统", "msg": "欢迎来到 Python 极客聊天室！"})
        except:
            return

        while server_running:
            data = recv_packet(client_socket)
            if not data: break

            # 更新心跳
            with data_lock:
                if client_socket in clients_manager:
                    clients_manager[client_socket]["last_heartbeat"] = time.time()

            msg_type = data.get('type')
            if msg_type == 'heartbeat': continue

            # 更新昵称并检测是否需要推送用户列表
            name = data.get('from', '未知')
            name_changed = False
            with data_lock:
                if client_socket in clients_manager:
                    old_name = clients_manager[client_socket]["name"]
                    if old_name != name:
                        clients_manager[client_socket]["name"] = name
                        # 更新反向索引
                        if old_name in name_to_socket and name_to_socket[old_name] == client_socket:
                            del name_to_socket[old_name]
                        name_to_socket[name] = client_socket
                        name_changed = True

            if name_changed:
                broadcast_user_list()

            # --- 文本消息 (支持私聊) ---
            if msg_type == 'text':
                msg_content = data['msg']
                # 简单的消息过滤
                if config['security']['enable_message_filter'] and len(msg_content) > config['security'][
                    'max_message_length']:
                    msg_content = msg_content[:config['security']['max_message_length']] + "..."

                target = data.get('target', '所有人')
                log_message(name, msg_content, 'text', target)

                if global_mute or addr[0] in muted_ips:
                    send_packet(client_socket, {"type": "text", "from": "系统", "msg": "⛔ 发言失败：你已被禁言"})
                    continue

                if target == '所有人':
                    broadcast({"type": "text", "from": name, "target": "所有人", "msg": msg_content}, client_socket)
                else:
                    # 私聊逻辑（使用反向索引优化查找）
                    target_socket = name_to_socket.get(target)

                    if target_socket and target_socket in clients_manager:
                        try:
                            # 发给目标
                            send_packet(target_socket, {"type": "text", "from": name, "target": "你", "msg": msg_content})
                            # 发回给自己（确认）
                            send_packet(client_socket, {"type": "text", "from": name, "target": target, "msg": msg_content})
                        except Exception as e:
                            logger.error(f"私聊发送失败: {e}")
                            send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 发送失败：网络错误"})
                    else:
                        send_packet(client_socket,
                                    {"type": "text", "from": "系统", "msg": f"❌ 发送失败：用户 {target} 不在线"})

            # --- 文件上传（增强安全验证）---
            elif msg_type == 'file_upload':
                filename = data.get('filename')
                b64_data = data.get('data')

                try:
                    # 1. 验证文件名
                    filename = validate_filename(filename)
                    if not filename:
                        send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件名无效"})
                        continue

                    # 2. 验证文件扩展名
                    if not validate_file_extension(filename):
                        send_packet(client_socket, {"type": "text", "from": "系统",
                                                   "msg": f"❌ 不支持的文件类型。允许的类型: {', '.join(ALLOWED_EXTENSIONS)}"})
                        continue

                    # 3. 验证文件大小
                    decoded_data = base64.b64decode(b64_data)
                    file_size = len(decoded_data)
                    if file_size > MAX_FILE_SIZE:
                        send_packet(client_socket, {"type": "text", "from": "系统",
                                                   "msg": f"❌ 文件过大，最大允许 {MAX_FILE_SIZE/1024/1024:.1f}MB"})
                        continue

                    # 4. 保存文件
                    file_id = str(uuid.uuid4())
                    file_path = os.path.join(TEMP_FILES_DIR, file_id)
                    with open(file_path, 'wb') as f:
                        f.write(decoded_data)

                    # 5. 记录文件信息
                    with data_lock:
                        uploaded_files[file_id] = {
                            "filename": filename,
                            "path": file_path,
                            "uploader": name,
                            "upload_time": time.time(),
                            "size": file_size
                        }

                    # 6. 广播通知
                    broadcast({"type": "file_notify", "file_id": file_id, "filename": filename, "from": name}, None)
                    log_message(name, filename, 'file')
                    send_packet(client_socket, {"type": "text", "from": "系统",
                                               "msg": f"✅ 文件《{filename}》上传成功 ({file_size/1024:.1f}KB)"})
                    logger.info(f"文件上传: {filename} ({file_size} bytes) by {name}")
                except base64.binascii.Error as e:
                    logger.error(f"Base64解码失败: {e}")
                    send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件数据格式错误"})
                except Exception as e:
                    logger.error(f"文件处理失败: {e}")
                    send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件上传失败"})

            # --- 文件下载（改进异常处理）---
            elif msg_type == 'file_request':
                file_id = data.get('file_id')
                with data_lock:
                    file_info = uploaded_files.get(file_id)

                if file_info and os.path.exists(file_info['path']):
                    try:
                        with open(file_info['path'], 'rb') as f:
                            b64_data = base64.b64encode(f.read()).decode('utf-8')
                        send_packet(client_socket, {
                            "type": "file_response", "file_id": file_id,
                            "filename": file_info['filename'], "data": b64_data
                        })
                        logger.info(f"文件下载: {file_info['filename']} by {name}")
                    except IOError as e:
                        logger.error(f"读取文件失败: {e}")
                        send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件读取失败"})
                    except Exception as e:
                        logger.error(f"发送文件数据失败: {e}")
                        send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件发送失败"})
                else:
                    send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件不存在或已过期"})

    except ConnectionError as e:
        logger.warning(f"客户端连接错误: {addr[0]} - {e}")
    except Exception as e:
        logger.error(f"客户端处理异常: {addr[0]} - {e}")
    finally:
        with data_lock:
            if client_socket in clients_manager:
                # 清理反向索引
                name = clients_manager[client_socket]['name']
                if name in name_to_socket and name_to_socket[name] == client_socket:
                    del name_to_socket[name]
                del clients_manager[client_socket]
        try:
            client_socket.close()
        except Exception as e:
            logger.error(f"关闭客户端连接时出错: {e}")
        broadcast_user_list()  # 用户离开，更新列表
        log_system("退出", f"{addr[0]} 已离开", Color.FAIL)


# ====================== 管理员控制台 ======================
def print_status_table():
    """打印实时状态表"""
    with data_lock:
        print(f"\n{Color.HEADER}{'=' * 70}")
        print(f"{'服务器实时监控面板':^66}")
        print('=' * 70 + Color.ENDC)
        print(f"{Color.BOLD} {'IP地址':<16} {'端口':<8} {'状态':<12} {'昵称':<20} {Color.ENDC}")
        print(f"{Color.GREY}-" * 70 + Color.ENDC)

        if not clients_manager:
            print(f"{Color.GREY}{'当前无人在线...':^70}{Color.ENDC}")
        else:
            for sock, info in clients_manager.items():
                addr = info['addr']
                name = info['name']
                tags = []
                if addr[0] in banned_ips: tags.append("封禁")
                if addr[0] in muted_ips: tags.append("禁言")
                if global_mute: tags.append("全员禁")

                status_str = f"[{','.join(tags)}]" if tags else "[正常]"
                status_color = Color.FAIL if tags else Color.GREEN

                print(f" {addr[0]:<16} {addr[1]:<8} {status_color}{status_str:<12}{Color.ENDC} {name:<20}")

        gm_state = f"{Color.FAIL}[全员禁言开启]{Color.ENDC}" if global_mute else f"{Color.GREEN}[自由发言模式]{Color.ENDC}"
        max_conn = config.get('server', {}).get('max_connections', 50)
        print(f"{Color.HEADER}{'=' * 70}{Color.ENDC}")
        print(f"在线: {len(clients_manager)}/{max_conn} 人 | 模式: {gm_state}")
        print(f"文件: {len(uploaded_files)} 个 | 黑名单: {len(banned_ips)} 个\n")


def admin_console():
    """管理员控制台"""
    global global_mute, admin_authenticated, server_running
    time.sleep(1)

    # 密码验证
    if config['admin']['password_enabled']:
        print(f"\n{Color.WARNING}>>> 管理员控制台需要密码验证{Color.ENDC}")
        for attempt in range(3):
            password = input(f"{Color.CYAN}请输入管理员密码: {Color.ENDC}").strip()
            if verify_admin_password(password):
                admin_authenticated = True
                print(f"{Color.GREEN}>>> 验证成功！欢迎管理员{Color.ENDC}")
                break
            else:
                print(f"{Color.FAIL}>>> 密码错误 ({attempt + 1}/3){Color.ENDC}")

        if not admin_authenticated:
            print(f"{Color.FAIL}>>> 验证失败，控制台已锁定{Color.ENDC}")
            return

    print(f"\n{Color.WARNING}>>> 管理员控制台已就绪。输入 'help' 获取指令。{Color.ENDC}")

    while server_running:
        try:
            cmd = input().strip()
            if not cmd: continue

            parts = cmd.split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            if command in ("help", "?"):
                print(f"""{Color.BLUE}
┌────────────────── [ 指令手册 ] ──────────────────┐
│ status     查看面板      list       简单列表     │
│ say <msg>  系统广播      clear      清屏         │
│ kick <IP>  踢人          ban <IP>   封禁IP       │
│ unban <IP> 解封          banlist    黑名单       │
│ mute <IP>  禁言          unmute <IP> 解禁言      │
│ gmute      全员禁言      ungmute    取消全员禁   │
│ files      文件列表      save       保存数据     │
│ shutdown   关机                                  │
└──────────────────────────────────────────────────┘{Color.ENDC}""")

            elif command == "status":
                print_status_table()

            elif command == "list":
                with data_lock:
                    print(f"\n{Color.CYAN}在线用户 ({len(clients_manager)}):{Color.ENDC}")
                    for sock, info in clients_manager.items():
                        print(f"  - {info['name']} ({info['addr'][0]})")
                print()

            elif command == "clear":
                print("\033[H\033[J", end="")
                print(f"{Color.HEADER}>>> 控制台已清空{Color.ENDC}")

            elif command == "say" and args:
                broadcast({"type": "text", "from": "【系统广播】", "msg": args, "target": "所有人"}, None)
                log_message("【系统广播】", args)

            elif command == "kick" and args:
                target_ip = args.split()[0]
                kicked_count = 0
                with data_lock:
                    for sock, info in list(clients_manager.items()):
                        if info['addr'][0] == target_ip:
                            try:
                                send_packet(sock, {"type": "text", "from": "系统", "msg": "你已被移出房间！"})
                                sock.close()
                            except Exception as e:
                                logger.error(f"踢出用户时出错: {e}")
                            # 清理反向索引
                            name = info['name']
                            if name in name_to_socket and name_to_socket[name] == sock:
                                del name_to_socket[name]
                            del clients_manager[sock]
                            kicked_count += 1
                broadcast_user_list()
                print(f"{Color.GREEN}>>> 已踢出 {kicked_count} 人{Color.ENDC}")

            elif command == "ban" and args:
                ip = args.split()[0]
                banned_ips.add(ip)
                with data_lock:
                    for sock, info in list(clients_manager.items()):
                        if info['addr'][0] == ip:
                            try:
                                send_packet(sock, {"type": "text", "from": "系统", "msg": "你已被永久封禁！"})
                                sock.close()
                            except Exception as e:
                                logger.error(f"封禁用户时出错: {e}")
                            # 清理反向索引
                            name = info['name']
                            if name in name_to_socket and name_to_socket[name] == sock:
                                del name_to_socket[name]
                            del clients_manager[sock]
                broadcast_user_list()
                print(f"{Color.FAIL}>>> IP {ip} 已加入黑名单{Color.ENDC}")
                save_persistent_data()

            elif command == "unban" and args:
                ip = args.split()[0]
                banned_ips.discard(ip)
                print(f"{Color.GREEN}>>> 已解除封禁{Color.ENDC}")
                save_persistent_data()

            elif command == "banlist":
                print(f"\n{Color.HEADER}=== 黑名单列表 ==={Color.ENDC}")
                if banned_ips:
                    for ip in banned_ips:
                        print(f"  {Color.FAIL}{ip}{Color.ENDC}")
                else:
                    print(f"  {Color.GREY}(空){Color.ENDC}")
                print()

            elif command == "mute" and args:
                ip = args.split()[0]
                muted_ips.add(ip)
                print(f"{Color.WARNING}>>> IP {ip} 已被禁言{Color.ENDC}")
                save_persistent_data()

            elif command == "unmute" and args:
                ip = args.split()[0]
                muted_ips.discard(ip)
                print(f"{Color.GREEN}>>> IP {ip} 已解除禁言{Color.ENDC}")
                save_persistent_data()

            elif command == "gmute":
                global_mute = True
                broadcast({"type": "text", "from": "系统", "msg": "管理员开启了全员禁言！", "target": "所有人"}, None)
                print(f"{Color.FAIL}>>> 全员禁言 ON{Color.ENDC}")

            elif command == "ungmute":
                global_mute = False
                broadcast({"type": "text", "from": "系统", "msg": "全员禁言已解除。", "target": "所有人"}, None)
                print(f"{Color.GREEN}>>> 全员禁言 OFF{Color.ENDC}")

            elif command == "files":
                with data_lock:
                    print(f"\n{Color.CYAN}已上传文件 ({len(uploaded_files)}):{Color.ENDC}")
                    if uploaded_files:
                        for fid, info in uploaded_files.items():
                            age = int(time.time() - info['upload_time'])
                            print(f"  - {info['filename']} ({info['size']/1024:.1f}KB) by {info['uploader']} [{age}s前]")
                    else:
                        print(f"  {Color.GREY}(无){Color.ENDC}")
                print()

            elif command == "save":
                save_persistent_data()
                print(f"{Color.GREEN}>>> 数据已保存{Color.ENDC}")

            elif command == "shutdown":
                print(f"{Color.FAIL}正在关闭服务器...{Color.ENDC}")
                logger.info("服务器正在关闭...")
                save_persistent_data()
                broadcast({"type": "text", "from": "系统", "msg": "服务器即将关闭...", "target": "所有人"}, None)
                time.sleep(1)

                server_running = False
                with data_lock:
                    for sock in list(clients_manager.keys()):
                        try:
                            sock.close()
                        except Exception as e:
                            logger.error(f"关闭连接时出错: {e}")

                logger.info("服务器已关闭")
                import sys
                sys.exit(0)

            else:
                print(f"{Color.GREY}未知指令 (输入 help 查看){Color.ENDC}")

        except KeyboardInterrupt:
            print(f"\n{Color.WARNING}>>> 使用 'shutdown' 命令关闭服务器{Color.ENDC}")
        except Exception as e:
            print(f"{Color.FAIL}控制台错误: {e}{Color.ENDC}")
            logger.error(f"控制台错误: {e}")


# ====================== 启动程序 ======================
def start_server():
    global server_running
    load_config()
    setup_logging()
    load_persistent_data()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((HOST, PORT))
        server.listen()
        print(f"{Color.HEADER}{'=' * 60}")
        print(f"   🚀 Python 聊天服务器 v9.0 (Enhanced Security Edition)")
        print(f"   🌍 监听地址: {HOST}:{PORT}")
        print(f"   📊 最大连接数: {config['server']['max_connections']}")
        print(f"   🔐 管理员密码保护: {'启用' if config['admin']['password_enabled'] else '禁用'}")
        print(f"   📁 文件大小限制: {MAX_FILE_SIZE/1024/1024:.1f}MB")
        print('=' * 60 + Color.ENDC)

        logger.info(f"服务器启动成功: {HOST}:{PORT}")

        # 启动后台线程
        threading.Thread(target=heartbeat_monitor, daemon=True).start()
        threading.Thread(target=admin_console, daemon=True).start()
        logger.info("心跳监测和管理员控制台已启动")

        while server_running:
            try:
                client, addr = server.accept()
                if addr[0] in banned_ips:
                    client.close();
                    continue

                with data_lock:
                    if len(clients_manager) >= config['server']['max_connections']:
                        client.close();
                        continue

                threading.Thread(target=handle_client, args=(client, addr), daemon=True).start()
            except OSError:
                if not server_running: break
    except Exception as e:
        logger.critical(f"启动失败: {e}")
    finally:
        server_running = False
        server.close()
        if os.path.exists(TEMP_FILES_DIR): shutil.rmtree(TEMP_FILES_DIR)
        save_persistent_data()


if __name__ == "__main__":
    start_server()