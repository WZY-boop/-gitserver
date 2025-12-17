# API 文档 - 消息协议说明

本文档详细说明了 Python 聊天服务器的消息协议和客户端开发指南。

## 目录

- [连接协议](#连接协议)
- [消息格式](#消息格式)
- [消息类型](#消息类型)
- [客户端开发指南](#客户端开发指南)
- [示例代码](#示例代码)

---

## 连接协议

### 基本信息
- **协议**: TCP
- **默认端口**: 3000
- **编码**: UTF-8
- **传输格式**: JSON

### 连接流程

```
客户端                                服务器
  |                                     |
  |-------- TCP 连接请求 -------------->|
  |                                     |
  |<------- 欢迎消息 -------------------|
  |                                     |
  |-------- 发送消息 ------------------>|
  |                                     |
  |<------- 广播消息 -------------------|
  |                                     |
  |-------- 心跳包 -------------------->|
  |                                     |
  |-------- 断开连接 ------------------>|
```

### 连接建立

1. 客户端连接到服务器的 IP:PORT
2. 服务器检查 IP 是否在黑名单中
3. 服务器检查当前连接数是否已满
4. 连接成功后，服务器发送欢迎消息

---

## 消息格式

所有消息使用 JSON 格式，通过 `chat_protocol` 模块的 `send_packet` 和 `recv_packet` 函数进行封装和解析。

### 基本消息结构

```json
{
  "type": "消息类型",
  "from": "发送者昵称",
  "msg": "消息内容",
  "timestamp": 1234567890
}
```

### 字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| `type` | string | 是 | 消息类型（text/file/heartbeat） |
| `from` | string | 是 | 发送者昵称 |
| `msg` | string | 否 | 消息内容（文本消息时必需） |
| `filename` | string | 否 | 文件名（文件消息时必需） |
| `filedata` | string | 否 | 文件数据（Base64 编码） |
| `timestamp` | number | 否 | 时间戳（可选） |

---

## 消息类型

### 1. 文本消息 (text)

用于发送普通文本消息。

**客户端发送：**
```json
{
  "type": "text",
  "from": "Alice",
  "msg": "Hello, World!"
}
```

**服务器处理：**
- 检查发送者是否被禁言
- 过滤消息内容（长度限制）
- 广播给所有其他客户端

**服务器响应（广播给其他客户端）：**
```json
{
  "type": "text",
  "from": "Alice",
  "msg": "Hello, World!"
}
```

**禁言时的响应：**
```json
{
  "type": "text",
  "from": "系统",
  "msg": "⛔ 发言失败：你已被禁言"
}
```

---

### 2. 文件消息 (file)

用于发送文件。

**客户端发送：**
```json
{
  "type": "file",
  "from": "Alice",
  "filename": "document.pdf",
  "filedata": "base64_encoded_data_here..."
}
```

**服务器处理：**
- 检查发送者是否被禁言
- 记录文件传输日志
- 广播给所有其他客户端

**服务器响应（广播）：**
```json
{
  "type": "file",
  "from": "Alice",
  "filename": "document.pdf",
  "filedata": "base64_encoded_data_here..."
}
```

---

### 3. 心跳包 (heartbeat)

用于保持连接活跃，防止超时断开。

**客户端发送：**
```json
{
  "type": "heartbeat",
  "from": "Alice"
}
```

**服务器处理：**
- 更新客户端的最后心跳时间
- 不进行广播
- 不返回响应

**心跳配置：**
- 心跳间隔：30 秒（可在 config.json 中配置）
- 超时时间：90 秒（可在 config.json 中配置）

---

### 4. 系统消息

服务器发送给客户端的系统通知。

**欢迎消息：**
```json
{
  "type": "text",
  "from": "系统",
  "msg": "欢迎来到 Python 极客聊天室！"
}
```

**封禁通知：**
```json
{
  "type": "text",
  "from": "系统",
  "msg": "🚫 你的IP已被服务器封禁"
}
```

**服务器满：**
```json
{
  "type": "text",
  "from": "系统",
  "msg": "⚠️ 服务器已满，请稍后再试"
}
```

**心跳超时：**
```json
{
  "type": "text",
  "from": "系统",
  "msg": "心跳超时，连接已断开"
}
```

**系统广播：**
```json
{
  "type": "text",
  "from": "【系统广播】",
  "msg": "服务器将在 5 分钟后重启"
}
```

---

## 客户端开发指南

### 必需实现的功能

#### 1. chat_protocol 模块

客户端需要实现 `chat_protocol.py` 模块，包含以下函数：

```python
def send_packet(socket, data_dict):
    """
    发送消息包到服务器

    参数:
        socket: socket 对象
        data_dict: 字典格式的消息数据

    返回:
        成功返回 True，失败抛出异常
    """
    pass

def recv_packet(socket):
    """
    从服务器接收消息包

    参数:
        socket: socket 对象

    返回:
        字典格式的消息数据，连接断开返回 None
    """
    pass
```

#### 2. 连接管理

```python
import socket
from chat_protocol import send_packet, recv_packet

# 连接到服务器
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect(('127.0.0.1', 3000))

# 接收欢迎消息
welcome = recv_packet(client)
print(welcome['msg'])
```

#### 3. 发送消息

```python
# 发送文本消息
message = {
    "type": "text",
    "from": "MyUsername",
    "msg": "Hello, everyone!"
}
send_packet(client, message)
```

#### 4. 接收消息

```python
import threading

def receive_messages(client):
    while True:
        try:
            data = recv_packet(client)
            if not data:
                break

            if data['type'] == 'text':
                print(f"{data['from']}: {data['msg']}")
            elif data['type'] == 'file':
                print(f"{data['from']} 发送了文件: {data['filename']}")
        except Exception as e:
            print(f"接收消息出错: {e}")
            break

# 启动接收线程
recv_thread = threading.Thread(target=receive_messages, args=(client,))
recv_thread.daemon = True
recv_thread.start()
```

#### 5. 心跳机制

```python
import time
import threading

def send_heartbeat(client, username):
    while True:
        try:
            heartbeat = {
                "type": "heartbeat",
                "from": username
            }
            send_packet(client, heartbeat)
            time.sleep(30)  # 每 30 秒发送一次
        except Exception as e:
            print(f"心跳发送失败: {e}")
            break

# 启动心跳线程
heartbeat_thread = threading.Thread(target=send_heartbeat, args=(client, "MyUsername"))
heartbeat_thread.daemon = True
heartbeat_thread.start()
```

---

## 示例代码

### 完整的客户端示例

```python
import socket
import threading
import time
from chat_protocol import send_packet, recv_packet

class ChatClient:
    def __init__(self, host='127.0.0.1', port=3000):
        self.host = host
        self.port = port
        self.socket = None
        self.username = None
        self.running = False

    def connect(self, username):
        """连接到服务器"""
        self.username = username
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            self.socket.connect((self.host, self.port))
            self.running = True

            # 接收欢迎消息
            welcome = recv_packet(self.socket)
            print(welcome['msg'])

            # 启动接收线程
            recv_thread = threading.Thread(target=self._receive_messages)
            recv_thread.daemon = True
            recv_thread.start()

            # 启动心跳线程
            heartbeat_thread = threading.Thread(target=self._send_heartbeat)
            heartbeat_thread.daemon = True
            heartbeat_thread.start()

            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False

    def _receive_messages(self):
        """接收消息线程"""
        while self.running:
            try:
                data = recv_packet(self.socket)
                if not data:
                    break

                if data['type'] == 'text':
                    print(f"\n{data['from']}: {data['msg']}")
                elif data['type'] == 'file':
                    print(f"\n{data['from']} 发送了文件: {data['filename']}")
            except Exception as e:
                if self.running:
                    print(f"接收消息出错: {e}")
                break

        self.disconnect()

    def _send_heartbeat(self):
        """心跳线程"""
        while self.running:
            try:
                heartbeat = {
                    "type": "heartbeat",
                    "from": self.username
                }
                send_packet(self.socket, heartbeat)
                time.sleep(30)
            except Exception as e:
                if self.running:
                    print(f"心跳发送失败: {e}")
                break

    def send_message(self, message):
        """发送文本消息"""
        try:
            data = {
                "type": "text",
                "from": self.username,
                "msg": message
            }
            send_packet(self.socket, data)
        except Exception as e:
            print(f"发送消息失败: {e}")

    def send_file(self, filename, filedata):
        """发送文件"""
        try:
            data = {
                "type": "file",
                "from": self.username,
                "filename": filename,
                "filedata": filedata
            }
            send_packet(self.socket, data)
        except Exception as e:
            print(f"发送文件失败: {e}")

    def disconnect(self):
        """断开连接"""
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        print("已断开连接")

# 使用示例
if __name__ == "__main__":
    client = ChatClient('127.0.0.1', 3000)

    username = input("请输入昵称: ")
    if client.connect(username):
        print("连接成功！输入消息发送，输入 'quit' 退出。")

        while True:
            message = input()
            if message.lower() == 'quit':
                break
            client.send_message(message)

        client.disconnect()
```

---

## chat_protocol 实现示例

### 简单的 JSON 协议实现

```python
import json
import struct

def send_packet(sock, data_dict):
    """
    发送 JSON 消息包
    格式: [4字节长度][JSON数据]
    """
    try:
        # 将字典转换为 JSON 字符串
        json_data = json.dumps(data_dict, ensure_ascii=False)
        json_bytes = json_data.encode('utf-8')

        # 发送数据长度（4字节，大端序）
        length = struct.pack('>I', len(json_bytes))
        sock.sendall(length)

        # 发送 JSON 数据
        sock.sendall(json_bytes)
        return True
    except Exception as e:
        raise Exception(f"发送数据失败: {e}")

def recv_packet(sock):
    """
    接收 JSON 消息包
    返回: 字典对象，连接断开返回 None
    """
    try:
        # 接收数据长度（4字节）
        length_bytes = _recv_exact(sock, 4)
        if not length_bytes:
            return None

        # 解析长度
        length = struct.unpack('>I', length_bytes)[0]

        # 接收 JSON 数据
        json_bytes = _recv_exact(sock, length)
        if not json_bytes:
            return None

        # 解析 JSON
        json_data = json_bytes.decode('utf-8')
        return json.loads(json_data)
    except Exception as e:
        return None

def _recv_exact(sock, n):
    """
    精确接收 n 字节数据
    """
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data
```

---

## 错误处理

### 常见错误及处理

| 错误 | 原因 | 处理方式 |
|------|------|----------|
| 连接被拒绝 | IP 被封禁 | 联系管理员解封 |
| 连接超时 | 服务器未响应 | 检查网络和服务器状态 |
| 服务器已满 | 达到最大连接数 | 稍后重试 |
| 心跳超时 | 网络不稳定 | 重新连接 |
| 发言失败 | 被禁言 | 联系管理员 |

### 异常处理建议

```python
try:
    send_packet(socket, message)
except ConnectionError:
    print("连接已断开，尝试重连...")
    reconnect()
except Exception as e:
    print(f"发送失败: {e}")
```

---

## 安全建议

1. **输入验证**: 客户端应验证用户输入，防止注入攻击
2. **消息长度**: 限制消息长度，防止内存溢出
3. **心跳机制**: 必须实现心跳，避免被服务器断开
4. **错误处理**: 妥善处理所有异常，避免程序崩溃
5. **重连机制**: 实现自动重连，提升用户体验

---

## 版本兼容性

- **当前版本**: v6.0
- **协议版本**: 1.0
- **最低 Python 版本**: 3.7+

---

## 更新日志

### v6.0 (2025-12-17)
- 添加心跳机制
- 添加消息过滤
- 改进错误处理

### v5.0
- 初始版本
- 基础消息协议

---

## 技术支持

如有问题，请参考：
- [README.md](README.md) - 项目说明
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - 故障排查
- [DEPLOYMENT.md](DEPLOYMENT.md) - 部署指南
