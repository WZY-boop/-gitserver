import socket
import threading
import time
import json
import logging
import hashlib
from datetime import datetime
from logging.handlers import RotatingFileHandler
from chat_protocol import send_packet, recv_packet

# === 全局配置与数据 ===
config = {}
banned_ips = set()  # IP 黑名单
muted_ips = set()  # 个人禁言列表
global_mute = False  # 全员禁言开关
server_running = True  # 服务器运行状态
admin_authenticated = False  # 管理员认证状态

HOST = '0.0.0.0'
PORT = 3000

# 核心数据结构
clients_data = []  # 格式: [socket, addr, username, last_heartbeat]
data_lock = threading.Lock()  # 线程锁：保护 clients_data 不被同时修改导致崩溃

# Logger 实例
logger = None


# ====================== 配置与初始化 ======================
def load_config():
    """加载配置文件"""
    global config, HOST, PORT
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        HOST = config['server']['host']
        PORT = config['server']['port']
        return True
    except FileNotFoundError:
        print("警告: config.json 未找到，使用默认配置")
        config = {
            "server": {"host": "0.0.0.0", "port": 3000, "max_connections": 50},
            "admin": {"password": "admin123", "password_enabled": True},
            "security": {"enable_message_filter": True, "max_message_length": 1000,
                        "heartbeat_interval": 30, "heartbeat_timeout": 90},
            "logging": {"level": "INFO", "file": "server.log", "max_bytes": 10485760, "backup_count": 5},
            "data": {"banned_ips_file": "banned_ips.json", "muted_ips_file": "muted_ips.json"}
        }
        return False
    except Exception as e:
        print(f"配置文件加载失败: {e}")
        return False


def setup_logging():
    """配置日志系统"""
    global logger
    logger = logging.getLogger('ChatServer')
    logger.setLevel(getattr(logging, config['logging']['level']))

    # 文件处理器（带轮转）
    file_handler = RotatingFileHandler(
        config['logging']['file'],
        maxBytes=config['logging']['max_bytes'],
        backupCount=config['logging']['backup_count'],
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))

    # 控制台处理器（保留彩色输出）
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(message)s'))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


def load_persistent_data():
    """加载持久化数据（黑名单、禁言列表）"""
    global banned_ips, muted_ips
    try:
        with open(config['data']['banned_ips_file'], 'r') as f:
            banned_ips = set(json.load(f))
        logger.info(f"已加载 {len(banned_ips)} 个封禁IP")
    except FileNotFoundError:
        logger.info("未找到封禁列表文件，从空列表开始")
    except Exception as e:
        logger.error(f"加载封禁列表失败: {e}")

    try:
        with open(config['data']['muted_ips_file'], 'r') as f:
            muted_ips = set(json.load(f))
        logger.info(f"已加载 {len(muted_ips)} 个禁言IP")
    except FileNotFoundError:
        logger.info("未找到禁言列表文件，从空列表开始")
    except Exception as e:
        logger.error(f"加载禁言列表失败: {e}")


def save_persistent_data():
    """保存持久化数据"""
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
    # 使用 SHA256 哈希比较（更安全）
    return hashlib.sha256(password.encode()).hexdigest() == hashlib.sha256(expected.encode()).hexdigest()


def filter_message(msg):
    """消息内容过滤"""
    if not config['security']['enable_message_filter']:
        return msg

    # 长度限制
    max_len = config['security']['max_message_length']
    if len(msg) > max_len:
        return msg[:max_len] + "...[已截断]"

    # 可以添加更多过滤规则（敏感词、特殊字符等）
    # 这里仅做示例
    return msg


# --- 极客风颜色配置 ---
class Color:
    HEADER = '\033[95m'  # 紫色
    BLUE = '\033[94m'  # 蓝色
    CYAN = '\033[96m'  # 青色
    GREEN = '\033[92m'  # 绿色
    WARNING = '\033[93m'  # 黄色 (文件/警告)
    FAIL = '\033[91m'  # 红色 (错误/断开)
    BOLD = '\033[1m'  # 加粗
    UNDERLINE = '\033[4m'  # 下划线
    GREY = '\033[90m'  # 灰色 (用于时间)
    ENDC = '\033[0m'  # 重置


def get_time():
    return datetime.now().strftime('%H:%M:%S')


def log_system(prefix, message, color=Color.ENDC):
    """打印系统级日志（带日志记录）"""
    formatted = f"{Color.GREY}[{get_time()}]{Color.ENDC} {color}{Color.BOLD}[{prefix}]{Color.ENDC} {message}"
    print(formatted)
    # 同时记录到日志文件（去除颜色代码）
    if logger:
        plain_message = f"[{prefix}] {message}"
        if "错误" in prefix or "异常" in prefix:
            logger.error(plain_message)
        elif "警告" in prefix or "拦截" in prefix:
            logger.warning(plain_message)
        else:
            logger.info(plain_message)


def log_message(name, msg, msg_type='text'):
    """
    美化版消息打印：
    [时间] 昵称 > 消息内容
    """
    ts = f"{Color.GREY}{get_time()}{Color.ENDC}"

    # 根据身份决定名字颜色
    if "管理员" in name or "Admin" in name:
        name_display = f"{Color.HEADER}{Color.BOLD}{name}{Color.ENDC}"  # 管理员紫色加粗
    else:
        name_display = f"{Color.CYAN}{name}{Color.ENDC}"  # 普通人青色

    # 根据消息类型决定内容颜色
    if msg_type == 'text':
        print(f"{ts} {name_display} {Color.GREY}>>{Color.ENDC} {msg}")
        if logger:
            logger.info(f"{name} >> {msg}")
    elif msg_type == 'file':
        print(f"{ts} {name_display} {Color.GREY}>>{Color.ENDC} {Color.WARNING}[文件] {msg} 📁{Color.ENDC}")
        if logger:
            logger.info(f"{name} >> [文件] {msg}")


# ====================== 核心功能 ======================

def print_status_table():
    """打印漂亮的实时状态表"""
    with data_lock:  # 加锁读取
        print(f"\n{Color.HEADER}{'=' * 70}")
        print(f"{'服务器实时监控面板':^66}")
        print('=' * 70 + Color.ENDC)
        print(f"{Color.BOLD} {'IP地址':<16} {'端口':<8} {'状态':<12} {'昵称':<20} {Color.ENDC}")
        print(f"{Color.GREY}-" * 70 + Color.ENDC)

        if not clients_data:
            print(f"{Color.GREY}{'当前无人在线...':^70}{Color.ENDC}")
        else:
            for _, addr, name, _ in clients_data:  # 注意：现在有4个元素
                tags = []
                if addr[0] in banned_ips:  tags.append("封禁")
                if addr[0] in muted_ips:   tags.append("禁言")
                if global_mute:            tags.append("全员禁")

                status_str = f"[{','.join(tags)}]" if tags else "[正常]"
                # 状态颜色
                status_color = Color.FAIL if tags else Color.GREEN

                print(f" {addr[0]:<16} {addr[1]:<8} {status_color}{status_str:<12}{Color.ENDC} {name:<20}")

        gm_state = f"{Color.FAIL}[全员禁言开启]{Color.ENDC}" if global_mute else f"{Color.GREEN}[自由发言模式]{Color.ENDC}"
        max_conn = config.get('server', {}).get('max_connections', 50)
        print(f"{Color.HEADER}{'=' * 70}{Color.ENDC}")
        print(f"在线: {len(clients_data)}/{max_conn} 人 | 模式: {gm_state}\n")


def broadcast(message_dict, sender_socket=None):
    """向所有客户端广播消息 (线程安全版，改进异常处理)"""
    with data_lock:
        # 使用切片 [:] 复制一份列表进行遍历，防止发送途中有人断开导致列表长度变化报错
        current_clients = clients_data[:]

    for sock, addr, _, _ in current_clients:
        if sock != sender_socket:
            try:
                send_packet(sock, message_dict)
            except ConnectionError as e:
                logger.warning(f"向 {addr[0]} 发送消息失败: 连接错误 - {e}")
            except Exception as e:
                logger.error(f"向 {addr[0]} 发送消息时发生异常: {e}")


# ====================== 心跳检测 ======================
def heartbeat_monitor():
    """心跳监测线程：定期检查客户端是否超时"""
    global server_running
    timeout = config['security']['heartbeat_timeout']

    while server_running:
        time.sleep(10)  # 每10秒检查一次
        current_time = time.time()

        with data_lock:
            for i in range(len(clients_data) - 1, -1, -1):
                sock, addr, name, last_heartbeat = clients_data[i]
                if current_time - last_heartbeat > timeout:
                    try:
                        send_packet(sock, {"type": "text", "from": "系统", "msg": "心跳超时，连接已断开"})
                        sock.close()
                    except Exception as e:
                        logger.error(f"关闭超时连接时出错: {e}")
                    clients_data.pop(i)
                    log_system("超时", f"{addr[0]} ({name}) 心跳超时已断开", Color.WARNING)


# ====================== 管理员控制台 ======================
def admin_console():
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

    print(f"\n{Color.WARNING}>>> 暴君控制台已就绪。输入 'help' 获取指令。{Color.ENDC}")

    while server_running:
        try:
            # 使用 input 会阻塞，但为了简单起见保留。
            # 为了防止日志冲刷掉输入提示，这里稍微做了一点视觉分离
            cmd = input().strip()

            if not cmd: continue

            parts = cmd.split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            if command in ("help", "?"):
                print(f"""{Color.BLUE}
┌────────────────── [ 指令手册 ] ──────────────────┐
│ status     查看面板      list       简单列表      │
│ say <msg>  系统广播      clear      清屏          │
│ kick <IP>  踢人          ban <IP>   封禁IP        │
│ unban <IP> 解封          banlist    黑名单        │
│ mute <IP>  禁言          unmute <IP> 解禁言       │
│ gmute      全员禁言      ungmute    取消全员禁    │
│ rename <IP> <名> 改名    shutdown   关机          │
└──────────────────────────────────────────────────┘{Color.ENDC}""")

            elif command == "status":
                print_status_table()
            elif command == "clear":
                print("\033[H\033[J", end="")  # ANSI 清屏码
                print(f"{Color.HEADER}>>> 控制台已清空{Color.ENDC}")

            elif command == "say" and args:
                broadcast({"type": "text", "from": "【系统广播】", "msg": args}, None)
                log_message("【系统广播】", args)

            elif command == "kick" and args:
                target_ip = args.split()[0]
                kicked_count = 0
                with data_lock:
                    # 倒序遍历以便安全移除
                    for i in range(len(clients_data) - 1, -1, -1):
                        sock, addr, _, _ = clients_data[i]
                        if addr[0] == target_ip:
                            try:
                                send_packet(sock, {"type": "text", "from": "系统", "msg": "你已被移出房间！"})
                                sock.close()
                                clients_data.pop(i)
                                kicked_count += 1
                            except Exception as e:
                                logger.error(f"踢出用户时出错: {e}")
                print(f"{Color.GREEN}>>> 已踢出 {kicked_count} 人{Color.ENDC}")

            elif command == "ban" and args:
                ip = args.split()[0]
                banned_ips.add(ip)
                # 立即踢出当前在线的该IP
                with data_lock:
                    for i in range(len(clients_data) - 1, -1, -1):
                        sock, addr, _, _ = clients_data[i]
                        if addr[0] == ip:
                            try:
                                send_packet(sock, {"type": "text", "from": "系统", "msg": "你已被永久封禁！"})
                                sock.close()
                            except Exception as e:
                                logger.error(f"踢出用户时出错: {e}")
                            clients_data.pop(i)
                print(f"{Color.FAIL}>>> IP {ip} 已加入黑名单{Color.ENDC}")
                save_persistent_data()  # 保存数据

            elif command == "unban" and args:
                banned_ips.discard(args.split()[0])
                print(f"{Color.GREEN}>>> 已解除封禁{Color.ENDC}")
                save_persistent_data()  # 保存数据

            elif command == "gmute":
                global_mute = True
                broadcast({"type": "text", "from": "系统", "msg": "管理员开启了全员禁言！"}, None)
                print(f"{Color.FAIL}>>> 全员禁言 ON{Color.ENDC}")

            elif command == "ungmute":
                global_mute = False
                broadcast({"type": "text", "from": "系统", "msg": "全员禁言已解除。"}, None)
                print(f"{Color.GREEN}>>> 全员禁言 OFF{Color.ENDC}")

            elif command == "mute" and args:
                ip = args.split()[0]
                muted_ips.add(ip)
                print(f"{Color.WARNING}>>> IP {ip} 已被禁言{Color.ENDC}")
                save_persistent_data()  # 保存数据

            elif command == "unmute" and args:
                ip = args.split()[0]
                muted_ips.discard(ip)
                print(f"{Color.GREEN}>>> IP {ip} 已解除禁言{Color.ENDC}")
                save_persistent_data()  # 保存数据

            elif command == "banlist":
                print(f"\n{Color.HEADER}=== 黑名单列表 ==={Color.ENDC}")
                if banned_ips:
                    for ip in banned_ips:
                        print(f"  {Color.FAIL}{ip}{Color.ENDC}")
                else:
                    print(f"  {Color.GREY}(空){Color.ENDC}")
                print()

            elif command == "rename" and args:
                try:
                    ip, new_name = args.split(maxsplit=1)
                    found = False
                    with data_lock:
                        for entry in clients_data:
                            if entry[1][0] == ip:
                                old_name = entry[2]
                                entry[2] = new_name
                                try:
                                    send_packet(entry[0],
                                                {"type": "text", "from": "系统", "msg": f"系统强制改名为: {new_name}"})
                                    broadcast({"type": "text", "from": "系统", "msg": f"'{old_name}' 改名为 '{new_name}'"},
                                              None)
                                except Exception as e:
                                    logger.error(f"改名时出错: {e}")
                                found = True
                    if found:
                        print(f"{Color.GREEN}>>> 改名成功{Color.ENDC}")
                    else:
                        print(f"{Color.WARNING}>>> 未找到IP{Color.ENDC}")
                except Exception as e:
                    print(f"格式错误: rename <IP> <新名字> - {e}")

            elif command == "shutdown":
                print(f"{Color.FAIL}正在关闭服务器...{Color.ENDC}")
                logger.info("服务器正在关闭...")
                save_persistent_data()  # 保存数据
                broadcast({"type": "text", "from": "系统", "msg": "服务器即将关闭..."}, None)
                time.sleep(1)

                # 优雅关闭所有连接
                global server_running
                server_running = False
                with data_lock:
                    for sock, _, _, _ in clients_data[:]:
                        try:
                            sock.close()
                        except Exception as e:
                            logger.error(f"关闭连接时出错: {e}")

                logger.info("服务器已关闭")
                import sys
                sys.exit(0)

            else:
                print(f"{Color.GREY}未知指令 (输入 help 查看){Color.ENDC}")

        except Exception as e:
            print(f"控制台错误: {e}")


# ====================== 客户端处理 ======================
def handle_client(client_socket, addr):
    # 初始数据（添加心跳时间戳）
    entry = [client_socket, addr, "未命名", time.time()]

    # 加锁添加用户
    with data_lock:
        clients_data.append(entry)

    log_system("连接", f"{addr[0]} 已加入", Color.GREEN)

    try:
        # 发送欢迎
        send_packet(client_socket, {"type": "text", "from": "系统", "msg": "欢迎来到 Python 极客聊天室！"})

        while server_running:
            data = recv_packet(client_socket)
            if not data: break

            # 更新心跳时间
            entry[3] = time.time()

            # 处理心跳包
            if data.get('type') == 'heartbeat':
                continue

            # 更新昵称
            name = data.get('from', '未知')
            entry[2] = name  # 更新列表中的名字

            # 1. 消息日志美化处理
            msg_type = data.get('type')
            if msg_type == 'text':
                # 消息过滤
                original_msg = data['msg']
                filtered_msg = filter_message(original_msg)
                data['msg'] = filtered_msg
                log_message(name, filtered_msg, 'text')
            elif msg_type == 'file':
                log_message(name, data['filename'], 'file')

            # 2. 禁言检查
            if global_mute or addr[0] in muted_ips:
                send_packet(client_socket, {"type": "text", "from": "系统", "msg": "⛔ 发言失败：你已被禁言"})
                log_system("拦截", f"{name} 尝试发言被拦截", Color.WARNING)
                continue

            # 3. 广播
            broadcast(data, client_socket)

    except ConnectionError as e:
        log_system("连接错误", f"{addr[0]} 连接中断: {e}", Color.FAIL)
        logger.error(f"客户端 {addr[0]} 连接错误: {e}")
    except Exception as e:
        log_system("错误", f"{addr[0]} 异常: {e}", Color.FAIL)
        logger.error(f"处理客户端 {addr[0]} 时发生异常: {e}")
    finally:
        try:
            client_socket.close()
        except Exception as e:
            logger.error(f"关闭客户端连接时出错: {e}")
        # 加锁移除用户
        with data_lock:
            if entry in clients_data:
                clients_data.remove(entry)
        log_system("退出", f"{addr[0]} 已离开", Color.FAIL)


# ====================== 启动程序 ======================
def start_server():
    global server_running

    # 1. 加载配置
    load_config()

    # 2. 设置日志系统
    setup_logging()

    # 3. 加载持久化数据
    load_persistent_data()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((HOST, PORT))
        server.listen()

        print(f"{Color.HEADER}{'=' * 60}")
        print(f"   🚀 Python 聊天服务器 v6.0 (Enhanced Edition)")
        print(f"   🌍 监听地址: {HOST}:{PORT}")
        print(f"   📊 最大连接数: {config['server']['max_connections']}")
        print(f"   🔐 管理员密码保护: {'启用' if config['admin']['password_enabled'] else '禁用'}")
        print('=' * 60 + Color.ENDC)

        logger.info(f"服务器启动成功: {HOST}:{PORT}")

        # 启动后台管理员线程
        threading.Thread(target=admin_console, daemon=True).start()

        # 启动心跳监测线程
        threading.Thread(target=heartbeat_monitor, daemon=True).start()
        logger.info("心跳监测线程已启动")

        while server_running:
            try:
                client, addr = server.accept()

                # 黑名单拦截 (连接的第一时间)
                if addr[0] in banned_ips:
                    try:
                        send_packet(client, {"type": "text", "from": "系统", "msg": "🚫 你的IP已被服务器封禁"})
                        client.close()
                    except Exception as e:
                        logger.error(f"拦截黑名单IP时出错: {e}")
                    log_system("封禁", f"已拦截黑名单 IP: {addr[0]}", Color.FAIL)
                    continue

                # 连接数限制
                with data_lock:
                    current_connections = len(clients_data)

                if current_connections >= config['server']['max_connections']:
                    try:
                        send_packet(client, {"type": "text", "from": "系统", "msg": "⚠️ 服务器已满，请稍后再试"})
                        client.close()
                    except Exception as e:
                        logger.error(f"拒绝连接时出错: {e}")
                    log_system("拒绝", f"服务器已满，拒绝 {addr[0]} 连接", Color.WARNING)
                    continue

                # 为每个客户端启动独立线程
                threading.Thread(target=handle_client, args=(client, addr), daemon=True).start()

            except OSError as e:
                if not server_running:
                    break  # 服务器正在关闭
                logger.error(f"接受连接时出错: {e}")

    except Exception as e:
        print(f"{Color.FAIL}严重错误: 服务器启动失败 - {e}{Color.ENDC}")
        logger.critical(f"服务器启动失败: {e}")
    finally:
        server.close()
        logger.info("服务器已停止")


if __name__ == "__main__":
    start_server()