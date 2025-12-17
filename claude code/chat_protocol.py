import json
import struct

def send_packet(sock, data_dict):
    """
    发送消息包到 socket
    协议格式: [Header: 4字节大端序整数 (内容长度)] + [Body: JSON 字节流]
    
    参数:
        sock: socket 对象
        data_dict: 要发送的字典数据
        
    返回:
        bool: 发送成功返回 True，失败返回 False
    """
    try:
        # 1. 将字典序列化为 JSON 字符串，再编码为 bytes
        json_str = json.dumps(data_dict, ensure_ascii=False)
        body_bytes = json_str.encode('utf-8')
        
        # 2. 创建包头：4字节，大端序(>)，无符号整数(I)，值为 body 的长度
        header = struct.pack('>I', len(body_bytes))
        
        # 3. 发送 Header + Body
        # sendall 会确保所有数据都发送出去，适合大文件传输
        sock.sendall(header + body_bytes)
        return True
    except Exception as e:
        # 在生产环境中这里可以记录日志
        # print(f"发送数据包失败: {e}") 
        return False

def recv_packet(sock):
    """
    从 socket 接收完整的消息包
    
    参数:
        sock: socket 对象
        
    返回:
        dict: 解析后的字典数据
        None: 如果连接断开或数据格式错误
    """
    try:
        # 1. 先接收 4 字节的包头
        header = _recv_exact(sock, 4)
        if not header:
            return None
            
        # 2. 解析包头，获取内容长度
        # struct.unpack 返回一个元组，取第一个元素
        body_len = struct.unpack('>I', header)[0]
        
        # 3. 根据长度接收剩下的数据体
        body_bytes = _recv_exact(sock, body_len)
        if not body_bytes:
            return None
            
        # 4. 解码并反序列化 JSON
        json_str = body_bytes.decode('utf-8')
        return json.loads(json_str)
        
    except (json.JSONDecodeError, struct.error, OSError) as e:
        # print(f"接收/解析数据包失败: {e}")
        return None

def _recv_exact(sock, num_bytes):
    """
    辅助函数：确保接收到指定长度的字节
    解决 TCP 拆包/半包问题
    """
    data = b''
    while len(data) < num_bytes:
        try:
            # 尝试接收剩余需要的字节数
            packet = sock.recv(num_bytes - len(data))
            if not packet:
                # 对端关闭了连接
                return None
            data += packet
        except OSError:
            return None
    return data