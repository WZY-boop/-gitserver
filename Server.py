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
import bcrypt
from datetime import datetime
from logging.handlers import RotatingFileHandler
from chat_protocol import send_packet, recv_packet, PROTOCOL_VERSION

# === 全局配置与数据 ===
config = {}
banned_ips = set()
muted_ips = set()
global_mute = False
server_running = True
admin_authenticated = False
config_last_modified = 0  # 配置文件最后修改时间

HOST = '0.0.0.0'
PORT = 3000

# sock -> {"addr": addr, "name": str, "last_heartbeat": float}
clients_manager = {}
name_to_socket = {}  # 反向索引：name -> socket (优化私聊查找)

# 连接速率限制（防DDoS）
from collections import defaultdict
connection_attempts = defaultdict(list)  # IP -> [时间戳列表]54
MAX_CONNECTIONS_PER_IP = 5  # 每个IP最多同时5个连接
MAX_ATTEMPTS_PER_MINUTE = 10  # 每分钟最多10次连接尝试

TEMP_FILES_DIR = "server_temp_files"
if not os.path.exists(TEMP_FILES_DIR):
    os.makedirs(TEMP_FILES_DIR)

uploaded_files = {}  # file_id -> info
FILE_EXPIRE_SECONDS = 24 * 3600
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {'.txt', '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.zip', '.rar', '.doc', '.docx', '.xls', '.xlsx'}

# 敏感词过滤列表
BANNED_WORDS = ['fuck', 'shit', '傻逼', '操你妈', '去死', '垃圾']

# 用户名规则
MAX_NAME_LENGTH = 20
RESERVED_NAMES = {"系统", "服务器", "【系统广播】", "所有人", "你", "未命名"}

data_lock = threading.Lock()
logger = None
last_cleanup_time = 0


# ====================== 配置与日志 (保持不变) ======================
def load_config():
    global config, HOST, PORT, FILE_EXPIRE_SECONDS, config_last_modified
    try:
        # 记录配置文件修改时间
        config_last_modified = os.path.getmtime('config.json')
        
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


def hot_reload_config():
    """热加载配置文件（仅加载可以动态更新的配置项）"""
    global config, FILE_EXPIRE_SECONDS, config_last_modified
    
    try:
        current_mtime = os.path.getmtime('config.json')
        
        # 检查文件是否被修改
        if current_mtime <= config_last_modified:
            return False
        
        config_last_modified = current_mtime
        
        with open('config.json', 'r', encoding='utf-8') as f:
            new_config = json.load(f)
        
        # 只更新可以热加载的配置项
        old_config = config.copy()
        
        # 更新安全配置
        if 'security' in new_config:
            config['security'] = new_config['security']
            if 'file_expire_hours' in new_config['security']:
                FILE_EXPIRE_SECONDS = new_config['security']['file_expire_hours'] * 3600
        
        # 更新管理员配置
        if 'admin' in new_config:
            config['admin'] = new_config['admin']
        
        # 更新数据文件路径配置
        if 'data' in new_config:
            config['data'] = new_config['data']
        
        # 重新加载禁言和封禁列表
        load_persistent_data()
        
        logger.info("配置文件已热加载")
        
        # 广播配置更新通知（如果有重要变更）
        if old_config.get('security', {}).get('max_message_length') != config.get('security', {}).get('max_message_length'):
            broadcast({
                "type": "text", 
                "from": "系统", 
                "msg": f"配置已更新：消息长度限制调整为 {config['security']['max_message_length']} 字符",
                "target": "所有人"
            }, None)
        
        return True
        
    except FileNotFoundError:
        logger.warning("配置文件不存在，跳过热加载")
        return False
    except json.JSONDecodeError as e:
        logger.error(f"配置文件格式错误，热加载失败: {e}")
        return False
    except Exception as e:
        logger.error(f"配置热加载失败: {e}")
        return False


def config_file_watcher():
    """配置文件监听线程，定期检查配置文件变化"""
    CHECK_INTERVAL = 5  # 每5秒检查一次
    
    while server_running:
        time.sleep(CHECK_INTERVAL)
        
        try:
            if hot_reload_config():
                log_system("配置", "检测到配置文件变化，已自动重载", Color.WARNING)
        except Exception as e:
            if logger:
                logger.error(f"配置监听线程错误: {e}")


def setup_logging():
    global logger
    # 更鲁棒地读取日志配置，避免 KeyError 或 小写 level 导致异常
    logger = logging.getLogger('ChatServer')
    level_name = config.get('logging', {}).get('level', 'INFO')
    level = getattr(logging, level_name.upper(), logging.INFO)
    logger.setLevel(level)
    log_cfg = config.get('logging', {})
    log_file = log_cfg.get('file', 'server.log')
    max_bytes = log_cfg.get('max_bytes', 10 * 1024 * 1024)
    backup_count = log_cfg.get('backup_count', 5)
    file_handler = RotatingFileHandler(log_file, maxBytes=max_bytes,
                                      backupCount=backup_count, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter('%(message)s'))
    # 避免重复添加 handler（例如在交互式重载时）
    if logger.handlers:
        logger.handlers = []
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
    """验证管理员密码（使用 bcrypt）"""
    if not config['admin']['password_enabled']:
        return True
    
    try:
        # 获取存储的 bcrypt 哈希
        stored_hash = config['admin'].get('password_hash', '')
        
        # 如果是旧版 SHA256 格式（64字符十六进制），自动升级
        if stored_hash and len(stored_hash) == 64 and all(c in '0123456789abcdef' for c in stored_hash.lower()):
            logger.warning("检测到旧版 SHA256 密码格式，建议更新配置文件使用 bcrypt")
            # 兼容模式：使用明文密码（如果存在）
            if 'password' in config['admin']:
                return password == config['admin']['password']
            return False
        
        # 如果没有哈希但有明文密码（首次运行或旧配置）
        if not stored_hash and 'password' in config['admin']:
            # 生成新的 bcrypt 哈希并提示管理员更新配置
            new_hash = bcrypt.hashpw(config['admin']['password'].encode('utf-8'), bcrypt.gensalt())
            logger.warning(f"建议将以下 bcrypt 哈希值更新到 config.json 的 password_hash 字段：")
            logger.warning(f"  \"password_hash\": \"{new_hash.decode('utf-8')}\"")
            # 临时使用明文比较
            return password == config['admin']['password']
        
        # 标准 bcrypt 验证
        if stored_hash:
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
        
        logger.error("未配置管理员密码")
        return False
        
    except Exception as e:
        logger.error(f"密码验证失败: {e}")
        return False


def validate_filename(filename):
    """验证并清理文件名

    安全措施：
    1. 使用 os.path.basename 移除路径
    2. Unicode 规范化防止编码绕过
    3. 过滤控制字符和不可见字符
    4. 检查空文件名和纯特殊字符文件名
    5. 限制文件名长度
    """
    import unicodedata

    if not filename or not isinstance(filename, str):
        return ""

    # Unicode 规范化（NFC 形式），防止编码绕过攻击
    filename = unicodedata.normalize('NFC', filename)

    # 移除路径，只保留文件名
    filename = os.path.basename(filename)

    # 过滤控制字符和不可见字符（保留可打印字符）
    filename = "".join(ch for ch in filename if ch.isprintable() and ch not in '\x00\x1f')

    # 移除危险字符序列
    dangerous_chars = ['..', '/', '\\', '\x00', ':', '*', '?', '"', '<', '>', '|']
    for char in dangerous_chars:
        filename = filename.replace(char, '')

    # 去除首尾空白
    filename = filename.strip()

    # 检查是否为空或只包含点号
    if not filename or filename.replace('.', '') == '':
        return ""

    # 限制文件名长度（255 是大多数文件系统的限制）
    if len(filename) > 200:
        # 保留扩展名
        name, ext = os.path.splitext(filename)
        max_name_len = 200 - len(ext)
        filename = name[:max_name_len] + ext

    return filename


def validate_file_extension(filename):
    """验证文件扩展名"""
    _, ext = os.path.splitext(filename.lower())
    return ext in ALLOWED_EXTENSIONS


# Aho-Corasick 敏感词过滤器（高效多模式匹配）
class AhoCorasick:
    """Aho-Corasick 自动机，用于高效的多模式字符串匹配"""

    def __init__(self):
        self.goto = [{}]  # goto 函数
        self.fail = [0]   # fail 函数
        self.output = [set()]  # 输出函数
        self.state_count = 1

    def add_pattern(self, pattern):
        """添加一个模式串"""
        state = 0
        for char in pattern:
            if char not in self.goto[state]:
                self.goto.append({})
                self.fail.append(0)
                self.output.append(set())
                self.goto[state][char] = self.state_count
                self.state_count += 1
            state = self.goto[state][char]
        self.output[state].add(pattern)

    def build(self):
        """构建 fail 函数"""
        from collections import deque
        queue = deque()

        # 初始化深度为1的状态
        for char, state in self.goto[0].items():
            self.fail[state] = 0
            queue.append(state)

        # BFS 构建 fail 函数
        while queue:
            curr = queue.popleft()
            for char, next_state in self.goto[curr].items():
                queue.append(next_state)
                fail_state = self.fail[curr]
                while fail_state != 0 and char not in self.goto[fail_state]:
                    fail_state = self.fail[fail_state]
                self.fail[next_state] = self.goto[fail_state].get(char, 0)
                self.output[next_state] |= self.output[self.fail[next_state]]

    def search(self, text):
        """搜索文本中的所有匹配，返回 [(start, end, pattern), ...]"""
        results = []
        state = 0
        for i, char in enumerate(text):
            while state != 0 and char not in self.goto[state]:
                state = self.fail[state]
            state = self.goto[state].get(char, 0)
            for pattern in self.output[state]:
                start = i - len(pattern) + 1
                results.append((start, i + 1, pattern))
        return results


# 初始化敏感词过滤器
sensitive_filter = None


def init_sensitive_filter():
    """初始化敏感词过滤器"""
    global sensitive_filter
    sensitive_filter = AhoCorasick()
    for word in BANNED_WORDS:
        sensitive_filter.add_pattern(word)
        # 添加变体（处理常见绕过方式）
        # 例如：傻 逼 -> 傻逼
        normalized = word.replace(' ', '').replace('-', '').replace('_', '')
        if normalized != word:
            sensitive_filter.add_pattern(normalized)
    sensitive_filter.build()


def filter_sensitive_words(message):
    """使用 Aho-Corasick 算法过滤敏感词"""
    global sensitive_filter
    if sensitive_filter is None:
        init_sensitive_filter()

    # 预处理：移除常见绕过字符进行检测
    normalized_msg = message.replace(' ', '').replace('-', '').replace('_', '')

    # 在原始消息中查找
    matches = sensitive_filter.search(message)
    # 在规范化消息中查找
    norm_matches = sensitive_filter.search(normalized_msg)

    if not matches and not norm_matches:
        return message

    # 构建替换映射
    result = list(message)
    for start, end, _ in matches:
        for i in range(start, end):
            if i < len(result):
                result[i] = '*'

    return ''.join(result)


def check_rate_limit(ip):
    """检查IP连接速率限制
    
    返回:
        (bool, str): (是否允许连接, 拒绝原因)
    """
    now = time.time()
    
    # 清理60秒前的记录
    connection_attempts[ip] = [t for t in connection_attempts[ip] if now - t < 60]
    
    # 检查每分钟连接次数
    if len(connection_attempts[ip]) >= MAX_ATTEMPTS_PER_MINUTE:
        return False, f"连接过于频繁，请稍后再试"
    
    # 检查同时连接数
    with data_lock:
        current_connections = sum(1 for info in clients_manager.values() if info['addr'][0] == ip)
        if current_connections >= MAX_CONNECTIONS_PER_IP:
            return False, f"该IP已达到最大连接数限制({MAX_CONNECTIONS_PER_IP})"
    
    # 记录本次连接尝试
    connection_attempts[ip].append(now)
    return True, ""


def sanitize_client_name(name):
    if not isinstance(name, str):
        return ""
    name = name.strip()
    if not name:
        return ""
    # 去除控制字符与 ANSI ESC，避免污染控制台输出
    name = "".join(ch for ch in name if ch.isprintable() and ch != "\x1b")
    name = name.replace("\r", "").replace("\n", "").replace("\t", "")
    if len(name) > MAX_NAME_LENGTH:
        name = name[:MAX_NAME_LENGTH]
    return name


def _allocate_unique_name_unlocked(base_name):
    base_name = sanitize_client_name(base_name)
    if not base_name or base_name in RESERVED_NAMES:
        base_name = "Guest"

    if base_name not in name_to_socket:
        return base_name

    idx = 2
    while True:
        suffix = f"_{idx}"
        candidate = base_name[: MAX_NAME_LENGTH - len(suffix)] + suffix
        if candidate not in name_to_socket:
            return candidate
        idx += 1


def assign_initial_name_if_needed(client_socket, proposed_name):
    """
    仅在该连接还未命名时，为其分配一个唯一且非保留的昵称。
    返回: (assigned_name, name_changed, notice_message_or_none)
    """
    proposed = sanitize_client_name(proposed_name)
    notice = None

    with data_lock:
        info = clients_manager.get(client_socket)
        if not info:
            return "未命名", False, None

        old_name = info.get("name", "未命名")
        if old_name != "未命名":
            return old_name, False, None

        if not proposed or proposed in RESERVED_NAMES:
            assigned = _allocate_unique_name_unlocked("Guest")
            notice = f"昵称不可用，已为你分配临时昵称：{assigned}"
        elif proposed in name_to_socket and name_to_socket.get(proposed) is not client_socket:
            assigned = _allocate_unique_name_unlocked(proposed)
            notice = f"昵称“{proposed}”已被占用，已为你分配：{assigned}"
        else:
            assigned = proposed

        info["name"] = assigned
        name_to_socket[assigned] = client_socket
        return assigned, True, notice


def cleanup_orphan_temp_files():
    """启动时清理上一次异常退出遗留的临时文件。"""
    if not os.path.exists(TEMP_FILES_DIR):
        return

    removed = 0
    for entry in os.listdir(TEMP_FILES_DIR):
        path = os.path.join(TEMP_FILES_DIR, entry)
        try:
            if os.path.isfile(path) or os.path.islink(path):
                os.remove(path)
                removed += 1
            elif os.path.isdir(path):
                shutil.rmtree(path)
                removed += 1
        except Exception as e:
            if logger:
                logger.warning(f"清理临时文件失败: {path} - {e}")

    if removed and logger:
        logger.info(f"启动清理：移除了 {removed} 个临时文件/目录")
    with data_lock:
        uploaded_files.clear()


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


def safe_send_packet(sock, packet):
    """安全发送数据包，处理竞态条件和连接错误

    返回: (success: bool, error_msg: str or None)
    """
    try:
        # 发送前检查 socket 是否仍然有效
        if sock.fileno() == -1:
            return False, "socket已关闭"
        send_packet(sock, packet)
        return True, None
    except (ConnectionError, OSError, BrokenPipeError) as e:
        return False, f"连接错误: {e}"
    except Exception as e:
        return False, f"发送失败: {e}"


def cleanup_dead_socket(sock):
    """清理死连接并关闭 socket"""
    with data_lock:
        if sock in clients_manager:
            name = clients_manager[sock]['name']
            if name in name_to_socket and name_to_socket[name] == sock:
                del name_to_socket[name]
            del clients_manager[sock]
    try:
        sock.close()
    except Exception:
        pass


def broadcast(packet, exclude_sock=None):
    # 快照当前连接，避免在持锁时执行网络 IO（可能阻塞）
    with data_lock:
        targets = [s for s in clients_manager.keys() if s is not exclude_sock]

    dead_sockets = []
    for sock in targets:
        success, _ = safe_send_packet(sock, packet)
        if not success:
            dead_sockets.append(sock)

    # 清理死连接（包括关闭 socket）
    for sock in dead_sockets:
        cleanup_dead_socket(sock)


def broadcast_user_list():
    """向所有客户端推送当前在线用户列表"""
    with data_lock:
        # 过滤掉初始连接还没发过包的 "未命名" 用户
        users = [info['name'] for info in clients_manager.values() if info['name'] != "未命名"]

    # 对列表去重并排序，为了美观
    users = sorted(list(set(users)))
    packet = {"type": "user_list", "users": users}
    broadcast(packet, None)  # 发给所有人


def check_disk_space(force_cleanup_threshold=100 * 1024 * 1024):
    """检查磁盘空间，空间不足时强制清理文件
    
    参数:
        force_cleanup_threshold: 强制清理阈值（字节），默认100MB
    
    返回:
        (bool, int): (是否空间充足, 剩余空间字节数)
    """
    try:
        stat = shutil.disk_usage(TEMP_FILES_DIR)
        if stat.free < force_cleanup_threshold:
            logger.warning(f"磁盘空间不足 ({stat.free / 1024 / 1024:.1f}MB)，强制清理文件")
            cleanup_expired_files(force=True)
            # 重新检查
            stat = shutil.disk_usage(TEMP_FILES_DIR)
        return stat.free >= force_cleanup_threshold, stat.free
    except Exception as e:
        logger.error(f"检查磁盘空间失败: {e}")
        return True, 0  # 出错时默认允许继续


def cleanup_expired_files(force=False):
    """清理过期文件
    
    参数:
        force: 是否强制清理（True时清理所有文件，不仅是过期的）
    """
    global uploaded_files
    now = time.time()
    with data_lock:
        if force:
            # 强制模式：按上传时间排序，优先删除最旧的文件
            sorted_files = sorted(uploaded_files.items(), key=lambda x: x[1]['upload_time'])
            # 删除一半的文件
            to_delete = [fid for fid, _ in sorted_files[:len(sorted_files) // 2 + 1]]
            expired = to_delete
        else:
            # 正常模式：只删除过期文件
            expired = [fid for fid, info in uploaded_files.items() if now - info['upload_time'] > FILE_EXPIRE_SECONDS]
        
        for fid in expired:
            path = uploaded_files[fid]['path']
            if os.path.exists(path):
                try:
                    os.remove(path)
                    logger.info(f"清理{'过期' if not force else ''}文件: {uploaded_files[fid]['filename']}")
                except Exception as e:
                    logger.error(f"删除文件失败: {e}")
            del uploaded_files[fid]
        if expired:
            logger.info(f"清理了 {len(expired)} 个文件 (强制模式: {force})")


def increment_download_count(file_id):
    """增加文件下载计数（不删除文件，让过期机制处理）"""
    with data_lock:
        if file_id in uploaded_files:
            uploaded_files[file_id]['download_count'] += 1
            filename = uploaded_files[file_id]['filename']
            count = uploaded_files[file_id]['download_count']
            logger.info(f"文件下载计数: {filename} (已下载 {count} 次)")


def cleanup_connection_attempts():
    """清理过期的连接尝试记录，防止内存泄漏"""
    now = time.time()
    expired_ips = []
    for ip, timestamps in list(connection_attempts.items()):
        # 清理60秒前的记录
        connection_attempts[ip] = [t for t in timestamps if now - t < 60]
        # 如果该IP没有任何记录了，标记为待删除
        if not connection_attempts[ip]:
            expired_ips.append(ip)

    # 删除空记录的IP
    for ip in expired_ips:
        del connection_attempts[ip]

    if expired_ips and logger:
        logger.debug(f"清理了 {len(expired_ips)} 个过期的连接记录")


def heartbeat_monitor():
    global last_cleanup_time
    # 动态调整检测间隔：取超时时间的1/10，最小5秒，最大30秒
    base_interval = config['security'].get('heartbeat_timeout', 90) / 10
    check_interval = max(5, min(30, base_interval))

    while server_running:
        time.sleep(check_interval)
        now = time.time()
        timeout = config['security']['heartbeat_timeout']

        need_update_list = False
        with data_lock:
            dead_sockets = [
                sock for sock, info in clients_manager.items()
                if now - info["last_heartbeat"] > timeout
            ]
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

        # 每5分钟清理一次过期文件和连接记录
        if now - last_cleanup_time > 300:
            cleanup_expired_files()
            cleanup_connection_attempts()
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
        except (ConnectionError, OSError) as e:
            logger.warning(f"发送欢迎消息失败: {addr[0]} - {e}")
            return

        while server_running:
            try:
                data = recv_packet(client_socket)
                if not data: break
            except ConnectionResetError:
                logger.info(f"客户端强制断开连接: {addr[0]}")
                break
            except socket.timeout:
                logger.warning(f"接收数据超时: {addr[0]}")
                break
            except json.JSONDecodeError as e:
                logger.error(f"协议解析错误: {addr[0]} - {e}")
                continue
            except Exception as e:
                logger.error(f"接收数据异常: {addr[0]} - {e}")
                break

            # 更新心跳
            with data_lock:
                if client_socket in clients_manager:
                    clients_manager[client_socket]["last_heartbeat"] = time.time()

            msg_type = data.get('type')
            if msg_type == 'heartbeat': continue

            # 仅首次为该连接分配昵称（避免每包都能伪造/切换 from）
            proposed_name = data.get('from', '')
            name, name_changed, notice = assign_initial_name_if_needed(client_socket, proposed_name)
            if notice:
                try:
                    send_packet(client_socket, {"type": "text", "from": "系统", "msg": notice})
                except Exception:
                    pass
            if name_changed:
                broadcast_user_list()

            # --- 文本消息 (支持私聊) ---
            if msg_type == 'text':
                msg_content = data['msg']
                
                # 消息过滤：长度限制 + 敏感词过滤
                if config['security']['enable_message_filter']:
                    if len(msg_content) > config['security']['max_message_length']:
                        msg_content = msg_content[:config['security']['max_message_length']] + "..."
                    msg_content = filter_sensitive_words(msg_content)

                target = data.get('target', '所有人')
                log_message(name, msg_content, 'text', target)

                if global_mute or addr[0] in muted_ips:
                    try:
                        send_packet(client_socket, {"type": "text", "from": "系统", "msg": "⛔ 发言失败：你已被禁言"})
                    except Exception as e:
                        logger.error(f"发送禁言提示失败: {e}")
                    continue

                if target == '所有人':
                    broadcast({"type": "text", "from": name, "target": "所有人", "msg": msg_content}, client_socket)
                else:
                    # 私聊逻辑（对 name_to_socket 及 clients_manager 的访问加锁，发送在锁外进行）
                    with data_lock:
                        target_socket = name_to_socket.get(target)
                        target_online = (target_socket in clients_manager) if target_socket else False

                    if target_socket and target_online:
                        # 使用安全发送，处理竞态条件
                        success, err = safe_send_packet(target_socket, {
                            "type": "text", "from": name, "target": "你", "msg": msg_content
                        })
                        if success:
                            # 发回给自己（确认）
                            safe_send_packet(client_socket, {
                                "type": "text", "from": name, "target": target, "msg": msg_content
                            })
                        else:
                            logger.error(f"私聊发送失败: {err}")
                            # 清理可能已断开的目标连接
                            cleanup_dead_socket(target_socket)
                            safe_send_packet(client_socket, {
                                "type": "text", "from": "系统", "msg": "❌ 发送失败：对方连接已断开"
                            })
                    else:
                        safe_send_packet(client_socket, {
                            "type": "text", "from": "系统", "msg": f"❌ 发送失败：用户 {target} 不在线"
                        })

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
                            "size": file_size,
                            "download_count": 0  # 下载计数器
                        }

                    # 6. 广播通知
                    broadcast({"type": "file_notify", "file_id": file_id, "filename": filename, "from": name}, None)
                    log_message(name, filename, 'file')
                    send_packet(client_socket, {"type": "text", "from": "系统",
                                               "msg": f"✅ 文件《{filename}》上传成功 ({file_size/1024:.1f}KB)"})
                    logger.info(f"文件上传: {filename} ({file_size} bytes) by {name}")
                except base64.binascii.Error as e:
                    logger.error(f"Base64解码失败: {addr[0]} - {e}")
                    try:
                        send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件数据格式错误"})
                    except (ConnectionError, OSError):
                        pass
                except IOError as e:
                    logger.error(f"文件写入失败: {addr[0]} - {e}")
                    try:
                        send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件保存失败"})
                    except (ConnectionError, OSError):
                        pass
                except (MemoryError, ValueError) as e:
                    logger.error(f"文件处理失败（内存/数据错误）: {addr[0]} - {e}")
                    try:
                        send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件处理失败"})
                    except (ConnectionError, OSError):
                        pass

            # --- 文件下载（改进异常处理 + 下载后清理）---
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
                        
                        # 增加下载计数（不删除文件）
                        increment_download_count(file_id)
                        
                    except IOError as e:
                        logger.error(f"读取文件失败: {addr[0]} - {e}")
                        try:
                            send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件读取失败"})
                        except (ConnectionError, OSError):
                            pass
                    except (ConnectionError, OSError) as e:
                        logger.error(f"发送文件数据失败（网络错误）: {addr[0]} - {e}")
                else:
                    try:
                        send_packet(client_socket, {"type": "text", "from": "系统", "msg": "❌ 文件不存在或已过期"})
                    except (ConnectionError, OSError) as e:
                        logger.error(f"发送错误提示失败: {e}")

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

            elif command == "reload":
                if hot_reload_config():
                    print(f"{Color.GREEN}>>> 配置已重新加载{Color.ENDC}")
                    log_system("配置", "管理员手动重载配置", Color.WARNING)
                else:
                    print(f"{Color.FAIL}>>> 配置重载失败，请检查日志{Color.ENDC}")

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
    cleanup_orphan_temp_files()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        server.bind((HOST, PORT))
        server.listen()
        print(f"{Color.HEADER}{'=' * 60}")
        print(f"   🚀 Python 聊天服务器 v9.0 (Enhanced Security Edition)")
        print(f"   🌍 监听地址: {HOST}:{PORT}")
        print(f"   📡 协议版本: {PROTOCOL_VERSION}")
        print(f"   📊 最大连接数: {config['server']['max_connections']}")
        print(f"   🔐 管理员密码保护: {'启用' if config['admin']['password_enabled'] else '禁用'}")
        print(f"   📁 文件大小限制: {MAX_FILE_SIZE/1024/1024:.1f}MB")
        print('=' * 60 + Color.ENDC)

        logger.info(f"服务器启动成功: {HOST}:{PORT}")

        # 启动后台线程
        threading.Thread(target=heartbeat_monitor, daemon=True).start()
        threading.Thread(target=admin_console, daemon=True).start()
        threading.Thread(target=config_file_watcher, daemon=True).start()
        logger.info("心跳监测、管理员控制台和配置监听已启动")

        while server_running:
            try:
                client, addr = server.accept()
                # 在接受后进行速率限制检查（防止连接风暴）
                allowed, reason = check_rate_limit(addr[0])
                if not allowed:
                    logger.warning(f"拒绝连接 {addr[0]}: {reason}")
                    try:
                        send_packet(client, {"type": "text", "from": "系统", "msg": reason})
                    except Exception:
                        pass
                    client.close()
                    continue

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
