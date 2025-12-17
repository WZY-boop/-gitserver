# Python 聊天服务器 v9.0

[![Python Version](https://img.shields.io/badge/python-3.7+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-9.0-orange.svg)](https://github.com/yourusername/chat-server)

一个功能完整、安全可靠的多线程 TCP 聊天服务器，支持实时消息、私聊、文件传输、管理员控制台等功能。

## ✨ 特性

### 核心功能
- 🔄 多线程架构，支持多客户端并发连接
- 💬 实时消息广播 + 点对点私聊
- 📁 安全的文件传输系统（10MB 限制，类型白名单）
- 👥 在线用户列表实时推送
- 🎨 彩色终端输出，美观易读
- 📝 完整的日志系统（文件 + 控制台，支持轮转）

### 管理功能
- 🎛️ 强大的管理员控制台
- 🔐 密码保护（SHA256 哈希验证）
- 🚫 IP 黑名单管理
- 🔇 用户禁言（个人/全员）
- 📊 实时监控面板
- 💾 手动数据保存
- 📂 文件列表查看

### 安全特性
- 🛡️ 文件大小限制（10MB）
- ✅ 文件类型白名单验证
- 🔒 文件名安全过滤（防路径遍历）
- 🚦 连接数限制（防止资源耗尽）
- 💓 心跳检测（自动清理僵尸连接）
- 🔍 消息内容过滤和长度限制
- 💾 数据持久化（黑名单/禁言列表）
- 📋 详细的审计日志
- ⚡ O(1) 私聊查找优化

## 快速开始

### 环境要求
- Python 3.7+
- 依赖模块：`chat_protocol`（需自行实现或提供）

### 安装

1. 克隆或下载项目文件
```bash
cd "d:\Python\Python project\claude code"
```

2. 确保 `chat_protocol.py` 存在并实现了以下函数：
   - `send_packet(socket, dict)` - 发送消息包
   - `recv_packet(socket)` - 接收消息包

### 配置

编辑 `config.json` 文件：

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 3000,
    "max_connections": 50
  },
  "admin": {
    "password": "your_password_here",
    "password_enabled": true
  },
  "security": {
    "enable_message_filter": true,
    "max_message_length": 1000,
    "heartbeat_interval": 30,
    "heartbeat_timeout": 90
  },
  "logging": {
    "level": "INFO",
    "file": "server.log",
    "max_bytes": 10485760,
    "backup_count": 5
  },
  "data": {
    "banned_ips_file": "banned_ips.json",
    "muted_ips_file": "muted_ips.json"
  }
}
```

### 启动服务器

```bash
python Server.py
```

首次启动时，如果启用了密码保护，需要输入管理员密码（默认：`54server`）。

## 🎛️ 管理员命令

启动服务器后，在控制台输入以下命令：

### 基础命令
| 命令 | 说明 |
|------|------|
| `help` / `?` | 显示命令帮助 |
| `status` | 查看实时监控面板 |
| `list` | 简单用户列表 |
| `clear` | 清空控制台 |
| `save` | 手动保存数据 |
| `shutdown` | 优雅关闭服务器 |

### 用户管理
| 命令 | 说明 |
|------|------|
| `kick <IP>` | 踢出指定 IP 的用户 |
| `ban <IP>` | 封禁 IP（永久） |
| `unban <IP>` | 解除封禁 |
| `banlist` | 查看黑名单列表 |

### 禁言管理
| 命令 | 说明 |
|------|------|
| `mute <IP>` | 禁言指定 IP |
| `unmute <IP>` | 解除禁言 |
| `gmute` | 开启全员禁言 |
| `ungmute` | 关闭全员禁言 |

### 系统操作
| 命令 | 说明 |
|------|------|
| `say <消息>` | 发送系统广播 |
| `files` | 查看已上传文件列表 |

## 使用示例

### 启动服务器
```bash
$ python Server.py

============================================================
   🚀 Python 聊天服务器 v9.0 (Enhanced Security Edition)
   🌍 监听地址: 0.0.0.0:3000
   📊 最大连接数: 50
   🔐 管理员密码保护: 启用
   📁 文件大小限制: 10.0MB
============================================================

>>> 管理员控制台需要密码验证
请输入管理员密码: ********
>>> 验证成功！欢迎管理员

>>> 管理员控制台已就绪。输入 'help' 获取指令。
```

### 查看在线用户
```bash
status

======================================================================
                        服务器实时监控面板
======================================================================
 IP地址            端口     状态         昵称
----------------------------------------------------------------------
 192.168.1.100    54321    [正常]       Alice
 192.168.1.101    54322    [禁言]       Bob
======================================================================
在线: 2/50 人 | 模式: [自由发言模式]
文件: 3 个 | 黑名单: 0 个
```

### 查看文件列表
```bash
files

已上传文件 (3):
  - document.pdf (245.3KB) by Alice [120s前]
  - image.png (89.7KB) by Bob [300s前]
  - report.docx (156.2KB) by Alice [450s前]
```

### 封禁用户
```bash
ban 192.168.1.101
>>> IP 192.168.1.101 已加入黑名单
```

## 📁 文件结构

```
chat-server/
├── Server.py              # 主服务器程序 (v9.0)
├── chat_protocol.py       # 消息协议模块（需自行实现）
├── config.json            # 配置文件
├── server.log             # 日志文件（自动生成）
├── server_temp_files/     # 临时文件目录（自动生成）
├── banned_ips.json        # 黑名单数据（自动生成）
├── muted_ips.json         # 禁言列表（自动生成）
├── README.md              # 项目说明（本文件）
├── API.md                 # API 文档
├── DEPLOYMENT.md          # 部署指南
└── TROUBLESHOOTING.md     # 故障排查指南
```

## 日志系统

服务器会自动记录所有重要事件到 `server.log` 文件：

- 用户连接/断开
- 消息发送
- 管理员操作
- 错误和异常
- 系统事件

日志文件支持自动轮转（默认 10MB，保留 5 个备份）。

## 数据持久化

以下数据会自动保存到 JSON 文件：

- **banned_ips.json** - IP 黑名单
- **muted_ips.json** - 禁言用户列表

服务器重启后会自动加载这些数据。

## 安全建议

1. **修改默认密码**：编辑 `config.json`，修改 `admin.password`
2. **限制访问**：使用防火墙限制可访问的 IP 范围
3. **定期备份**：备份配置文件和数据文件
4. **监控日志**：定期检查 `server.log` 查找异常活动
5. **更新依赖**：保持 Python 和依赖库为最新版本

## 性能优化

### 当前配置适用场景
- 小到中等规模（50-100 并发连接）
- 局域网或小型互联网应用

### 大规模部署建议
- 使用 `asyncio` 重写（支持数千并发）
- 部署负载均衡器
- 使用 Redis 存储会话数据
- 启用消息队列（如 RabbitMQ）

## 故障排查

遇到问题？查看 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 获取详细的故障排查指南。

## API 文档

查看 [API.md](API.md) 了解消息协议和客户端开发指南。

## 部署指南

查看 [DEPLOYMENT.md](DEPLOYMENT.md) 了解生产环境部署的最佳实践。

## 📊 版本历史

### v9.0 (2025-12-17) - Enhanced Security Edition
**新增功能：**
- ✨ 点对点私聊功能
- ✨ 在线用户列表实时推送
- ✨ 安全的文件传输系统
- ✨ 文件大小限制（10MB）
- ✨ 文件类型白名单验证
- ✨ 文件名安全过滤
- ✨ 文件列表查看命令
- ✨ 手动数据保存命令

**性能优化：**
- ⚡ O(1) 私聊查找（反向索引）
- ⚡ 优化的文件清理机制
- ⚡ 改进的心跳检测

**安全加固：**
- 🔒 完善的异常处理
- 🔒 详细的错误日志
- 🔒 Base64 解码验证
- 🔒 路径遍历防护

### v8.0
- 基础文件传输
- 用户列表推送
- 私聊功能原型

### v6.0
- 配置文件支持
- logging 日志系统
- 管理员密码保护
- 数据持久化
- 心跳检测机制

### v5.0
- 基础聊天功能
- 管理员控制台
- 彩色终端输出

## 🔧 技术栈

- **语言**: Python 3.7+
- **架构**: 多线程 TCP Socket
- **日志**: logging + RotatingFileHandler
- **数据**: JSON 持久化
- **安全**: SHA256 密码哈希

## 📈 性能指标

| 指标 | 数值 |
|------|------|
| 最大并发连接 | 50（可配置） |
| 文件大小限制 | 10MB |
| 心跳超时 | 90秒 |
| 日志轮转 | 10MB/文件 |
| 私聊查找 | O(1) |

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

### 贡献指南
1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 📧 联系方式

- 项目地址：[GitHub](https://github.com/yourusername/chat-server)
- 问题反馈：[Issues](https://github.com/yourusername/chat-server/issues)
- 创建日期：2025-12-17

## ⚠️ 免责声明

本服务器仅用于学习和研究目的。在生产环境使用前，请进行充分的安全审计和压力测试。

## 🙏 致谢

感谢所有为本项目做出贡献的开发者！

---

**Made with ❤️ by Python Community**
