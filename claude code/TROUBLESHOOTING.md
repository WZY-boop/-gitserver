# 故障排查指南

本文档提供 Python 聊天服务器常见问题的诊断和解决方案。

## 目录

- [快速诊断](#快速诊断)
- [启动问题](#启动问题)
- [连接问题](#连接问题)
- [性能问题](#性能问题)
- [功能问题](#功能问题)
- [日志分析](#日志分析)
- [调试技巧](#调试技巧)
- [常见错误代码](#常见错误代码)

---

## 快速诊断

### 诊断检查清单

```bash
# 1. 检查服务状态
systemctl status chatserver

# 2. 检查端口监听
netstat -tuln | grep 3000

# 3. 检查进程
ps aux | grep Server.py

# 4. 查看最近日志
tail -50 /var/log/chatserver/server.log

# 5. 检查磁盘空间
df -h

# 6. 检查内存使用
free -h

# 7. 测试网络连接
telnet 127.0.0.1 3000
```

---

## 启动问题

### 问题 1: 服务无法启动

**症状：**
```
Failed to start chatserver.service
```

**可能原因及解决方案：**

#### 原因 1: 端口被占用

```bash
# 检查端口占用
netstat -tuln | grep 3000
# 或
lsof -i :3000

# 解决方案 1: 杀死占用进程
kill -9 <PID>

# 解决方案 2: 修改配置文件使用其他端口
nano /opt/chatserver/config.json
# 修改 "port": 3001
```

#### 原因 2: 配置文件错误

```bash
# 检查配置文件语法
python3 -c "import json; json.load(open('/opt/chatserver/config.json'))"

# 如果报错，修复 JSON 语法错误
nano /opt/chatserver/config.json
```

#### 原因 3: 权限问题

```bash
# 检查文件权限
ls -la /opt/chatserver/

# 修复权限
sudo chown -R chatserver:chatserver /opt/chatserver
sudo chmod 750 /opt/chatserver
sudo chmod 640 /opt/chatserver/*.py
```

#### 原因 4: Python 模块缺失

```bash
# 检查 chat_protocol 模块
python3 -c "from chat_protocol import send_packet, recv_packet"

# 如果报错，确保模块存在
ls -la /opt/chatserver/chat_protocol.py
```

---

### 问题 2: 服务启动后立即退出

**症状：**
```
Active: failed (Result: exit-code)
```

**诊断步骤：**

```bash
# 查看详细错误信息
journalctl -u chatserver -n 50 --no-pager

# 手动运行查看错误
cd /opt/chatserver
python3 Server.py
```

**常见错误及解决：**

#### 错误 1: 配置文件未找到

```
警告: config.json 未找到，使用默认配置
```

**解决方案：**
```bash
# 确保配置文件存在
ls -la /opt/chatserver/config.json

# 如果不存在，创建配置文件
cp config.json.example /opt/chatserver/config.json
```

#### 错误 2: 日志目录不存在

```
FileNotFoundError: [Errno 2] No such file or directory: '/var/log/chatserver/server.log'
```

**解决方案：**
```bash
# 创建日志目录
sudo mkdir -p /var/log/chatserver
sudo chown chatserver:chatserver /var/log/chatserver
sudo chmod 750 /var/log/chatserver
```

---

### 问题 3: 管理员密码验证失败

**症状：**
```
>>> 密码错误 (3/3)
>>> 验证失败，控制台已锁定
```

**解决方案：**

```bash
# 方案 1: 临时禁用密码验证
nano /opt/chatserver/config.json
# 修改 "password_enabled": false

# 方案 2: 重置密码
nano /opt/chatserver/config.json
# 修改 "password": "new_password"

# 重启服务
sudo systemctl restart chatserver
```

---

## 连接问题

### 问题 4: 客户端无法连接

**症状：**
```
Connection refused
Connection timeout
```

**诊断步骤：**

```bash
# 1. 确认服务正在运行
systemctl status chatserver

# 2. 确认端口监听
netstat -tuln | grep 3000

# 3. 测试本地连接
telnet 127.0.0.1 3000

# 4. 测试远程连接
telnet <服务器IP> 3000
```

**可能原因及解决方案：**

#### 原因 1: 防火墙阻止

```bash
# Ubuntu/Debian
sudo ufw status
sudo ufw allow 3000/tcp

# CentOS/RHEL
sudo firewall-cmd --list-all
sudo firewall-cmd --permanent --add-port=3000/tcp
sudo firewall-cmd --reload

# Windows
netsh advfirewall firewall show rule name=all | findstr 3000
```

#### 原因 2: 监听地址错误

```bash
# 检查配置
grep "host" /opt/chatserver/config.json

# 应该是 "0.0.0.0" 而不是 "127.0.0.1"
# 修改配置
nano /opt/chatserver/config.json
# "host": "0.0.0.0"

# 重启服务
sudo systemctl restart chatserver
```

#### 原因 3: IP 被封禁

```bash
# 检查黑名单
cat /opt/chatserver/data/banned_ips.json

# 解除封禁
# 方法 1: 通过管理员控制台
# 输入: unban <IP>

# 方法 2: 直接编辑文件
nano /opt/chatserver/data/banned_ips.json
# 删除对应 IP
sudo systemctl restart chatserver
```

---

### 问题 5: 连接频繁断开

**症状：**
```
心跳超时，连接已断开
```

**可能原因及解决方案：**

#### 原因 1: 网络不稳定

```bash
# 增加心跳超时时间
nano /opt/chatserver/config.json
# 修改 "heartbeat_timeout": 180  # 从 90 增加到 180 秒

# 重启服务
sudo systemctl restart chatserver
```

#### 原因 2: 客户端未发送心跳

**解决方案：** 确保客户端实现了心跳机制（参考 [API.md](API.md)）

---

### 问题 6: 服务器已满，无法连接

**症状：**
```
⚠️ 服务器已满，请稍后再试
```

**解决方案：**

```bash
# 方案 1: 增加最大连接数
nano /opt/chatserver/config.json
# 修改 "max_connections": 100  # 根据服务器资源调整

# 方案 2: 检查是否有僵尸连接
# 查看当前连接数
netstat -an | grep :3000 | grep ESTABLISHED | wc -l

# 重启服务清理连接
sudo systemctl restart chatserver
```

---

## 性能问题

### 问题 7: 服务器响应缓慢

**症状：**
- 消息延迟
- 连接建立缓慢
- CPU 使用率高

**诊断步骤：**

```bash
# 1. 检查系统负载
uptime
top

# 2. 检查进程资源使用
top -p $(pgrep -f Server.py)

# 3. 检查网络连接数
netstat -an | grep :3000 | wc -l

# 4. 检查内存使用
free -h

# 5. 检查磁盘 I/O
iostat -x 1 5
```

**解决方案：**

#### 方案 1: 优化系统参数

```bash
# 参考 DEPLOYMENT.md 中的性能优化章节
sudo nano /etc/sysctl.conf
# 添加优化参数
sudo sysctl -p
```

#### 方案 2: 限制连接数

```bash
# 降低最大连接数
nano /opt/chatserver/config.json
# "max_connections": 50
```

#### 方案 3: 增加服务器资源

- 升级 CPU
- 增加内存
- 使用 SSD 硬盘

---

### 问题 8: 内存泄漏

**症状：**
- 内存使用持续增长
- 服务器最终崩溃

**诊断步骤：**

```bash
# 监控内存使用
watch -n 5 'ps aux | grep Server.py'

# 使用 memory_profiler（需要安装）
pip install memory_profiler
python -m memory_profiler Server.py
```

**临时解决方案：**

```bash
# 定期重启服务（临时方案）
# 添加到 crontab
0 3 * * * systemctl restart chatserver
```

**永久解决方案：**
- 检查代码中的循环引用
- 确保及时关闭 socket 连接
- 定期清理 clients_data 列表

---

## 功能问题

### 问题 9: 消息无法发送

**症状：**
```
⛔ 发言失败：你已被禁言
```

**解决方案：**

```bash
# 检查禁言列表
cat /opt/chatserver/data/muted_ips.json

# 解除禁言
# 方法 1: 通过管理员控制台
# 输入: unmute <IP>

# 方法 2: 直接编辑文件
nano /opt/chatserver/data/muted_ips.json
# 删除对应 IP
sudo systemctl restart chatserver

# 检查全员禁言状态
# 通过管理员控制台输入: status
```

---

### 问题 10: 管理员命令无响应

**症状：**
- 输入命令后无反应
- 控制台卡住

**可能原因及解决方案：**

#### 原因 1: 未通过密码验证

**解决方案：** 重启服务并正确输入密码

#### 原因 2: 输入阻塞

**解决方案：**
```bash
# 按 Ctrl+C 中断
# 重启服务
sudo systemctl restart chatserver
```

---

### 问题 11: 日志文件过大

**症状：**
```
磁盘空间不足
日志文件占用大量空间
```

**解决方案：**

```bash
# 方案 1: 手动清理日志
sudo truncate -s 0 /var/log/chatserver/server.log

# 方案 2: 配置日志轮转
sudo nano /etc/logrotate.d/chatserver
# 参考 DEPLOYMENT.md 中的配置

# 方案 3: 调整日志级别
nano /opt/chatserver/config.json
# "level": "WARNING"  # 从 INFO 改为 WARNING

# 方案 4: 减少日志保留数量
nano /opt/chatserver/config.json
# "backup_count": 3  # 从 5 改为 3
```

---

## 日志分析

### 查看日志的常用命令

```bash
# 实时查看日志
tail -f /var/log/chatserver/server.log

# 查看最近 100 行
tail -100 /var/log/chatserver/server.log

# 查看错误日志
grep ERROR /var/log/chatserver/server.log

# 查看警告日志
grep WARNING /var/log/chatserver/server.log

# 查看特定 IP 的日志
grep "192.168.1.100" /var/log/chatserver/server.log

# 统计错误数量
grep ERROR /var/log/chatserver/server.log | wc -l

# 查看今天的日志
grep "$(date +%Y-%m-%d)" /var/log/chatserver/server.log
```

### 日志级别说明

| 级别 | 说明 | 示例 |
|------|------|------|
| DEBUG | 调试信息 | 详细的变量值、函数调用 |
| INFO | 一般信息 | 用户连接、消息发送 |
| WARNING | 警告信息 | 心跳超时、连接失败 |
| ERROR | 错误信息 | 异常、崩溃 |
| CRITICAL | 严重错误 | 服务器启动失败 |

---

## 调试技巧

### 1. 启用详细日志

```bash
# 临时启用 DEBUG 级别
nano /opt/chatserver/config.json
# "level": "DEBUG"

# 重启服务
sudo systemctl restart chatserver

# 查看详细日志
tail -f /var/log/chatserver/server.log
```

### 2. 手动运行服务器

```bash
# 停止系统服务
sudo systemctl stop chatserver

# 手动运行（可以看到所有输出）
cd /opt/chatserver
python3 Server.py

# 按 Ctrl+C 停止
```

### 3. 使用 Python 调试器

```python
# 在 Server.py 中添加断点
import pdb

def handle_client(client_socket, addr):
    pdb.set_trace()  # 断点
    # ... 其他代码
```

### 4. 网络抓包

```bash
# 使用 tcpdump 抓包
sudo tcpdump -i any port 3000 -w capture.pcap

# 使用 Wireshark 分析
wireshark capture.pcap
```

### 5. 压力测试

```bash
# 使用 ab (Apache Bench) 测试
ab -n 1000 -c 100 http://127.0.0.1:3000/

# 使用自定义脚本测试
python test_client.py
```

---

## 常见错误代码

### Python 异常

| 异常 | 原因 | 解决方案 |
|------|------|----------|
| `ConnectionRefusedError` | 服务器未运行或端口错误 | 检查服务状态和端口 |
| `OSError: Address already in use` | 端口被占用 | 更换端口或杀死占用进程 |
| `PermissionError` | 权限不足 | 使用 sudo 或修改权限 |
| `FileNotFoundError` | 文件不存在 | 检查文件路径 |
| `JSONDecodeError` | JSON 格式错误 | 检查配置文件语法 |
| `ModuleNotFoundError` | 模块未安装 | 安装缺失的模块 |
| `KeyError` | 配置项缺失 | 补充配置文件 |

### 系统错误

| 错误代码 | 说明 | 解决方案 |
|---------|------|----------|
| Exit code 1 | 一般错误 | 查看日志详细信息 |
| Exit code 2 | 配置错误 | 检查配置文件 |
| Exit code 137 | 内存不足被杀死 | 增加内存或优化代码 |
| Exit code 143 | 正常终止（SIGTERM） | 无需处理 |

---

## 获取帮助

### 收集诊断信息

在寻求帮助前，请收集以下信息：

```bash
#!/bin/bash
# diagnostic.sh - 诊断信息收集脚本

echo "=== 系统信息 ==="
uname -a
python3 --version

echo -e "\n=== 服务状态 ==="
systemctl status chatserver

echo -e "\n=== 端口监听 ==="
netstat -tuln | grep 3000

echo -e "\n=== 进程信息 ==="
ps aux | grep Server.py

echo -e "\n=== 最近日志 ==="
tail -50 /var/log/chatserver/server.log

echo -e "\n=== 配置文件 ==="
cat /opt/chatserver/config.json

echo -e "\n=== 磁盘空间 ==="
df -h

echo -e "\n=== 内存使用 ==="
free -h

echo -e "\n=== 网络连接 ==="
netstat -an | grep :3000 | wc -l
```

运行脚本：
```bash
bash diagnostic.sh > diagnostic_report.txt
```

### 联系支持

提供以下信息：
1. 诊断报告（diagnostic_report.txt）
2. 完整的错误信息
3. 服务器版本（v6.0）
4. 操作系统版本
5. 复现步骤

---

## 预防措施

### 1. 定期维护

```bash
# 每周检查清单
- [ ] 查看日志文件大小
- [ ] 检查磁盘空间
- [ ] 检查内存使用
- [ ] 验证备份完整性
- [ ] 更新系统补丁
```

### 2. 监控告警

```bash
# 设置监控脚本（参考 DEPLOYMENT.md）
*/5 * * * * /opt/chatserver/monitor.sh
```

### 3. 定期备份

```bash
# 每天备份（参考 DEPLOYMENT.md）
0 2 * * * /opt/chatserver/backup.sh
```

### 4. 安全审计

```bash
# 每月检查
- [ ] 审查黑名单
- [ ] 检查异常登录
- [ ] 更新密码
- [ ] 检查文件权限
```

---

## 相关文档

- [README.md](README.md) - 项目说明
- [API.md](API.md) - API 文档
- [DEPLOYMENT.md](DEPLOYMENT.md) - 部署指南

---

**提示**：如果问题仍未解决，请启用 DEBUG 日志级别，收集详细信息后寻求技术支持。
