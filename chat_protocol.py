import json
import struct
import uuid
import time
import threading

# 协议版本号
PROTOCOL_VERSION = "1.0.0"

# 消息ID生成器（线程安全）
_msg_counter = 0
_msg_counter_lock = threading.Lock()


def generate_message_id():
    """生成唯一消息ID: 时间戳_计数器_随机数（线程安全）"""
    global _msg_counter
    with _msg_counter_lock:
        _msg_counter += 1
        counter = _msg_counter
    timestamp = int(time.time() * 1000)  # 毫秒级时间戳
    random_part = uuid.uuid4().hex[:8]
    return f"{timestamp}_{counter}_{random_part}"

def send_packet(sock, data_dict, add_metadata=True):
    """
    发送消息包到 socket。
    注意：遇到网络或序列化错误时让异常向上抛出，由调用方处理（不要吞掉）。
    协议格式: [4字节大端序长度] + [JSON UTF-8 bytes]

    参数:
        sock: socket 对象
        data_dict: 要发送的数据字典
        add_metadata: 是否自动添加消息ID和协议版本（默认True）
    """
    # 自动添加元数据
    if add_metadata:
        if 'msg_id' not in data_dict:
            data_dict['msg_id'] = generate_message_id()
        if 'protocol_version' not in data_dict:
            data_dict['protocol_version'] = PROTOCOL_VERSION

    json_str = json.dumps(data_dict, ensure_ascii=False)
    body_bytes = json_str.encode('utf-8')
    header = struct.pack('>I', len(body_bytes))
    # 发生错误时让异常抛出，服务器/客户端上层捕获并清理连接
    sock.sendall(header + body_bytes)
    return True

def recv_packet(sock):
    """
    从 socket 接收完整的消息包并返回解析后的 dict。
    返回 None 表示对端关闭或 IO 错误（例如 recv 返回空或 OSError）。
    注意：如果收到的 body 不是合法 JSON，`json.JSONDecodeError` 将向上抛出，调用者应显式处理协议错误。
    """
    header = _recv_exact(sock, 4)
    if not header:
        return None

    body_len = struct.unpack('>I', header)[0]
    # 简单防护：拒绝异常大或无效的长度，避免内存耗尽攻击
    if body_len <= 0 or body_len > 50 * 1024 * 1024:  # 50MB 上限
        raise struct.error("非法的包长度")

    body_bytes = _recv_exact(sock, body_len)
    if not body_bytes:
        return None

    json_str = body_bytes.decode('utf-8')
    # 让 JSONDecodeError 在此处向上抛出，调用方可以选择记录并忽略该包或断开客户端
    return json.loads(json_str)

def _recv_exact(sock, num_bytes):
    """
    确保接收指定字节数，若对端关闭或发生 IO 错误返回 None。
    """
    data = b''
    while len(data) < num_bytes:
        try:
            packet = sock.recv(num_bytes - len(data))
            if not packet:
                return None
            data += packet
        except OSError:
            return None
    return data