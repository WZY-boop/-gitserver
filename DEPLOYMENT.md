# 部署指南 - 生产环境配置

本文档提供 Python 聊天服务器在生产环境中部署的最佳实践和配置建议。

## 目录

- [部署前准备](#部署前准备)
- [系统要求](#系统要求)
- [安装部署](#安装部署)
- [生产环境配置](#生产环境配置)
- [安全加固](#安全加固)
- [性能优化](#性能优化)
- [监控与维护](#监控与维护)
- [备份与恢复](#备份与恢复)
- [高可用部署](#高可用部署)

---

## 部署前准备

### 检查清单

- [ ] 服务器硬件资源充足
- [ ] Python 3.7+ 已安装
- [ ] 防火墙规则已配置
- [ ] SSL 证书已准备（如需加密）
- [ ] 备份策略已制定
- [ ] 监控系统已就绪
- [ ] 应急预案已准备

### 环境评估

```bash
# 检查 Python 版本
python --version

# 检查可用内存
free -h

# 检查磁盘空间
df -h

# 检查网络端口
netstat -tuln | grep 3000
```

---

## 系统要求

### 最低配置

| 组件 | 要求 |
|------|------|
| CPU | 2 核心 |
| 内存 | 2 GB |
| 磁盘 | 10 GB |
| 网络 | 10 Mbps |
| 操作系统 | Linux/Windows Server |

### 推荐配置

| 组件 | 要求 |
|------|------|
| CPU | 4 核心+ |
| 内存 | 8 GB+ |
| 磁盘 | 50 GB SSD |
| 网络 | 100 Mbps+ |
| 操作系统 | Ubuntu 20.04 LTS / CentOS 8 |

### 并发连接估算

| 并发用户 | CPU | 内存 | 带宽 |
|---------|-----|------|------|
| 50 | 2 核 | 2 GB | 10 Mbps |
| 100 | 4 核 | 4 GB | 20 Mbps |
| 500 | 8 核 | 16 GB | 100 Mbps |
| 1000+ | 16 核+ | 32 GB+ | 1 Gbps+ |

---

## 安装部署

### 1. 创建专用用户

```bash
# 创建服务用户（Linux）
sudo useradd -r -s /bin/false chatserver
sudo mkdir -p /opt/chatserver
sudo chown chatserver:chatserver /opt/chatserver
```

### 2. 部署文件

```bash
# 复制文件到部署目录
sudo cp Server.py /opt/chatserver/
sudo cp chat_protocol.py /opt/chatserver/
sudo cp config.json /opt/chatserver/

# 设置权限
sudo chown -R chatserver:chatserver /opt/chatserver
sudo chmod 750 /opt/chatserver
sudo chmod 640 /opt/chatserver/*.py
sudo chmod 600 /opt/chatserver/config.json
```

### 3. 安装依赖

```bash
# 创建虚拟环境（推荐）
cd /opt/chatserver
python3 -m venv venv
source venv/bin/activate

# 安装依赖（如有 requirements.txt）
pip install -r requirements.txt
```

### 4. 配置防火墙

```bash
# Ubuntu/Debian (UFW)
sudo ufw allow 3000/tcp
sudo ufw reload

# CentOS/RHEL (firewalld)
sudo firewall-cmd --permanent --add-port=3000/tcp
sudo firewall-cmd --reload

# Windows
netsh advfirewall firewall add rule name="Chat Server" dir=in action=allow protocol=TCP localport=3000
```

---

## 生产环境配置

### config.json 优化

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 3000,
    "max_connections": 200
  },
  "admin": {
    "password": "STRONG_PASSWORD_HERE",
    "password_enabled": true
  },
  "security": {
    "enable_message_filter": true,
    "max_message_length": 500,
    "heartbeat_interval": 30,
    "heartbeat_timeout": 90
  },
  "logging": {
    "level": "WARNING",
    "file": "/var/log/chatserver/server.log",
    "max_bytes": 52428800,
    "backup_count": 10
  },
  "data": {
    "banned_ips_file": "/opt/chatserver/data/banned_ips.json",
    "muted_ips_file": "/opt/chatserver/data/muted_ips.json"
  }
}
```

### 关键配置说明

1. **日志级别**: 生产环境建议使用 `WARNING` 或 `ERROR`
2. **日志路径**: 使用系统标准日志目录
3. **最大连接数**: 根据服务器资源调整
4. **密码强度**: 使用强密码（至少 16 位，包含大小写字母、数字、特殊字符）

---

## 安全加固

### 1. 密码安全

```bash
# 生成强密码
openssl rand -base64 32

# 修改 config.json 中的密码
# 建议：定期更换密码（每 90 天）
```

### 2. 文件权限

```bash
# 限制配置文件权限
chmod 600 /opt/chatserver/config.json
chmod 600 /opt/chatserver/data/*.json

# 限制日志文件权限
chmod 640 /var/log/chatserver/server.log
```

### 3. 网络安全

```bash
# 仅允许特定 IP 访问（可选）
# 编辑 /etc/hosts.allow
echo "sshd: 192.168.1.0/24" >> /etc/hosts.allow

# 使用 iptables 限制访问
sudo iptables -A INPUT -p tcp --dport 3000 -s 192.168.1.0/24 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 3000 -j DROP
```

### 4. SSL/TLS 加密（推荐）

虽然当前版本不支持 SSL，但可以通过反向代理实现：

```nginx
# Nginx 配置示例
upstream chatserver {
    server 127.0.0.1:3000;
}

server {
    listen 443 ssl;
    server_name chat.example.com;

    ssl_certificate /etc/ssl/certs/chat.crt;
    ssl_certificate_key /etc/ssl/private/chat.key;

    location / {
        proxy_pass http://chatserver;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 5. 系统加固

```bash
# 禁用不必要的服务
sudo systemctl disable bluetooth
sudo systemctl disable cups

# 启用自动安全更新（Ubuntu）
sudo apt install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades

# 配置 SELinux（CentOS）
sudo setenforce 1
```

---

## 性能优化

### 1. 系统参数调优

```bash
# 编辑 /etc/sysctl.conf
sudo nano /etc/sysctl.conf

# 添加以下配置
net.core.somaxconn = 1024
net.ipv4.tcp_max_syn_backlog = 2048
net.ipv4.tcp_fin_timeout = 30
net.ipv4.tcp_keepalive_time = 300
net.ipv4.tcp_tw_reuse = 1

# 应用配置
sudo sysctl -p
```

### 2. 文件描述符限制

```bash
# 编辑 /etc/security/limits.conf
sudo nano /etc/security/limits.conf

# 添加以下行
chatserver soft nofile 65536
chatserver hard nofile 65536

# 验证
ulimit -n
```

### 3. Python 优化

```python
# 在 Server.py 开头添加
import sys
sys.setswitchinterval(0.005)  # 减少线程切换开销
```

### 4. 日志轮转优化

```bash
# 创建 logrotate 配置
sudo nano /etc/logrotate.d/chatserver

# 添加以下内容
/var/log/chatserver/*.log {
    daily
    rotate 30
    compress
    delaycompress
    notifempty
    create 640 chatserver chatserver
    sharedscripts
    postrotate
        systemctl reload chatserver > /dev/null 2>&1 || true
    endscript
}
```

---

## 监控与维护

### 1. 系统服务配置

创建 systemd 服务文件（Linux）：

```bash
sudo nano /etc/systemd/system/chatserver.service
```

```ini
[Unit]
Description=Python Chat Server
After=network.target

[Service]
Type=simple
User=chatserver
Group=chatserver
WorkingDirectory=/opt/chatserver
ExecStart=/opt/chatserver/venv/bin/python /opt/chatserver/Server.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# 安全选项
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/chatserver/data /var/log/chatserver

[Install]
WantedBy=multi-user.target
```

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable chatserver
sudo systemctl start chatserver
sudo systemctl status chatserver
```

### 2. 监控脚本

```bash
#!/bin/bash
# /opt/chatserver/monitor.sh

LOG_FILE="/var/log/chatserver/monitor.log"
SERVICE_NAME="chatserver"

# 检查服务状态
if ! systemctl is-active --quiet $SERVICE_NAME; then
    echo "[$(date)] 服务已停止，正在重启..." >> $LOG_FILE
    systemctl start $SERVICE_NAME

    # 发送告警（可选）
    # mail -s "Chat Server Down" admin@example.com < /dev/null
fi

# 检查端口
if ! netstat -tuln | grep -q ":3000 "; then
    echo "[$(date)] 端口 3000 未监听" >> $LOG_FILE
fi

# 检查磁盘空间
DISK_USAGE=$(df -h /opt/chatserver | awk 'NR==2 {print $5}' | sed 's/%//')
if [ $DISK_USAGE -gt 80 ]; then
    echo "[$(date)] 磁盘使用率超过 80%: ${DISK_USAGE}%" >> $LOG_FILE
fi

# 检查内存使用
MEM_USAGE=$(free | awk 'NR==2 {printf "%.0f", $3/$2*100}')
if [ $MEM_USAGE -gt 90 ]; then
    echo "[$(date)] 内存使用率超过 90%: ${MEM_USAGE}%" >> $LOG_FILE
fi
```

添加到 crontab：

```bash
# 每 5 分钟检查一次
*/5 * * * * /opt/chatserver/monitor.sh
```

### 3. 日志监控

```bash
# 实时查看日志
tail -f /var/log/chatserver/server.log

# 查看错误日志
grep ERROR /var/log/chatserver/server.log

# 统计连接数
grep "已加入" /var/log/chatserver/server.log | wc -l
```

### 4. 性能监控

```bash
# 监控进程资源使用
top -p $(pgrep -f Server.py)

# 监控网络连接
netstat -an | grep :3000 | wc -l

# 监控系统负载
uptime
```

---

## 备份与恢复

### 1. 备份策略

```bash
#!/bin/bash
# /opt/chatserver/backup.sh

BACKUP_DIR="/backup/chatserver"
DATE=$(date +%Y%m%d_%H%M%S)

# 创建备份目录
mkdir -p $BACKUP_DIR

# 备份配置文件
tar -czf $BACKUP_DIR/config_$DATE.tar.gz \
    /opt/chatserver/config.json \
    /opt/chatserver/data/*.json

# 备份日志（最近 7 天）
find /var/log/chatserver -name "*.log*" -mtime -7 \
    -exec tar -czf $BACKUP_DIR/logs_$DATE.tar.gz {} +

# 删除 30 天前的备份
find $BACKUP_DIR -name "*.tar.gz" -mtime +30 -delete

echo "[$(date)] 备份完成: $BACKUP_DIR"
```

添加到 crontab：

```bash
# 每天凌晨 2 点备份
0 2 * * * /opt/chatserver/backup.sh
```

### 2. 恢复流程

```bash
# 停止服务
sudo systemctl stop chatserver

# 恢复配置文件
tar -xzf /backup/chatserver/config_20251217_020000.tar.gz -C /

# 恢复数据文件
cp /backup/chatserver/data/*.json /opt/chatserver/data/

# 设置权限
sudo chown -R chatserver:chatserver /opt/chatserver

# 启动服务
sudo systemctl start chatserver
```

---

## 高可用部署

### 1. 负载均衡架构

```
                    ┌─────────────┐
                    │ Load Balancer│
                    │   (Nginx)    │
                    └──────┬───────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
       ┌────▼────┐    ┌────▼────┐   ┌────▼────┐
       │Server 1 │    │Server 2 │   │Server 3 │
       │:3001    │    │:3002    │   │:3003    │
       └─────────┘    └─────────┘   └─────────┘
            │              │              │
            └──────────────┼──────────────┘
                           │
                    ┌──────▼───────┐
                    │ Redis/DB     │
                    │ (共享状态)    │
                    └──────────────┘
```

### 2. Nginx 负载均衡配置

```nginx
upstream chatservers {
    least_conn;
    server 127.0.0.1:3001 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:3002 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:3003 max_fails=3 fail_timeout=30s;
}

server {
    listen 3000;

    location / {
        proxy_pass http://chatservers;
        proxy_next_upstream error timeout invalid_header http_500;
        proxy_connect_timeout 2s;
    }
}
```

### 3. 健康检查

```bash
#!/bin/bash
# /opt/chatserver/healthcheck.sh

HOST="127.0.0.1"
PORT="3000"

# TCP 端口检查
if timeout 2 bash -c "cat < /dev/null > /dev/tcp/$HOST/$PORT"; then
    echo "OK"
    exit 0
else
    echo "FAIL"
    exit 1
fi
```

---

## 故障排查

遇到问题？查看 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) 获取详细的故障排查指南。

---

## 更新升级

### 1. 升级流程

```bash
# 1. 备份当前版本
/opt/chatserver/backup.sh

# 2. 停止服务
sudo systemctl stop chatserver

# 3. 更新文件
sudo cp Server.py /opt/chatserver/Server.py.new
sudo mv /opt/chatserver/Server.py.new /opt/chatserver/Server.py

# 4. 测试配置
python /opt/chatserver/Server.py --test-config

# 5. 启动服务
sudo systemctl start chatserver

# 6. 验证
sudo systemctl status chatserver
tail -f /var/log/chatserver/server.log
```

### 2. 回滚流程

```bash
# 恢复备份
tar -xzf /backup/chatserver/config_YYYYMMDD_HHMMSS.tar.gz -C /
sudo systemctl restart chatserver
```

---

## 安全检查清单

部署完成后，请确认以下安全措施：

- [ ] 已修改默认管理员密码
- [ ] 配置文件权限正确（600）
- [ ] 防火墙规则已配置
- [ ] 日志记录正常工作
- [ ] 备份任务已配置
- [ ] 监控脚本已运行
- [ ] 系统服务自动启动
- [ ] 资源限制已设置
- [ ] SSL/TLS 已启用（如需要）
- [ ] 应急预案已准备

---

## 技术支持

如有问题，请参考：
- [README.md](README.md) - 项目说明
- [API.md](API.md) - API 文档
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - 故障排查

---

**注意**：本指南基于 v6.0 版本编写，不同版本可能有所差异。部署前请仔细阅读并根据实际情况调整。
