# SSH 部署 AI Teaching Agent 到远程服务器

## 项目概况

| 组件 | 技术 | 说明 |
|------|------|------|
| 后端 | FastAPI + Uvicorn | `backend_python/api_server.py` |
| 前端 | 单页 HTML | `frontend_web/index.html` |
| RAG | ChromaDB + sentence-transformers | 向量知识库 |
| PPT 引擎 | ppt-master-main | SVG → PPTX |
| 模型文件 | bge-small-zh-v1.5 | Embedding 模型（约 90MB） |

---

## 前置准备

### 你需要的信息

```
服务器 IP:          例如 123.45.67.89
SSH 端口:           默认 22
用户名:             例如 root 或 ubuntu
登录方式:           密码 或 SSH 密钥
```

### 服务器最低要求

| 项目 | 最低配置 | 推荐配置 |
|------|---------|---------|
| CPU | 2 核 | 4 核 |
| 内存 | 4 GB | 8 GB（Embedding 模型需要） |
| 磁盘 | 20 GB | 40 GB |
| 系统 | Ubuntu 20.04+ / CentOS 8+ | Ubuntu 22.04 LTS |
| Python | 3.9+ | 3.11 |

---

## 第一步：配置 SSH 连接

### 1.1 测试连接（密码方式）

```bash
# 在你的 Windows 终端 (PowerShell) 中执行
ssh username@你的服务器IP
```

### 1.2 配置 SSH 免密登录（推荐）

```powershell
# ① 在本机生成密钥对（如果还没有的话）
ssh-keygen -t ed25519 -C "your_email@example.com"

# ② 将公钥上传到服务器
# Windows 没有 ssh-copy-id，手动操作：
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh username@服务器IP "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"

# ③ 验证免密登录
ssh username@服务器IP
```

### 1.3 配置 SSH 快捷方式（可选但推荐）

在 `C:\Users\你的用户名\.ssh\config` 中添加：

```
Host myserver
    HostName 你的服务器IP
    User username
    Port 22
    IdentityFile ~/.ssh/id_ed25519
```

之后只需 `ssh myserver` 即可连接。

---

## 第二步：上传项目文件

有 **三种方式**，按推荐程度排序：

### 方式 A：通过 Git（⭐ 最推荐）

> 如果项目已经推送到 GitHub，这是最干净的方式。`.gitignore` 已经帮你排除了所有不需要的文件。

```bash
# 在服务器上执行
cd /opt
git clone https://github.com/你的用户名/你的仓库.git ai-teaching-agent
cd ai-teaching-agent
```

### 方式 B：通过 SCP 直传

```powershell
# 在本机 PowerShell 中执行
scp -r D:\PythonProject\PythonProjectest username@服务器IP:/opt/ai-teaching-agent
```

> ⚠️ SCP 会上传所有文件，包括 `__pycache__`、模型文件等。建议先手动排除，或使用 rsync。

### 方式 C：通过 rsync（最灵活）

```bash
# 需要先安装 rsync（通过 Git Bash 或 WSL）
rsync -avz --progress \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '.idea' \
  --exclude '.vscode' \
  --exclude '.trae' \
  --exclude '.gemini' \
  --exclude 'models--Qwen*' \
  --exclude '*.pptx' \
  --exclude 'backend_python/chat_history.db' \
  --exclude 'backend_python/chroma_db' \
  --exclude 'backend_python/images' \
  /d/PythonProject/PythonProjectest/ username@服务器IP:/opt/ai-teaching-agent/
```

---

## 第三步：服务器环境搭建

SSH 登录到服务器后，执行以下操作：

### 3.1 安装系统依赖

```bash
# Ubuntu / Debian
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git nginx

# CentOS / RHEL
sudo yum update -y
sudo yum install -y python3 python3-pip git nginx
```

### 3.2 创建 Python 虚拟环境

```bash
cd /opt/ai-teaching-agent
python3 -m venv venv
source venv/bin/activate
```

### 3.3 安装 Python 依赖

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3.4 配置环境变量

```bash
# 创建并编辑 .env 文件
nano .env
```

`.env` 内容（根据你的实际密钥填写）：

```env
IMAGE_BACKEND=qwen
QWEN_API_KEY=你的API密钥
QWEN_MODEL=wanx-v1
```

> ⚠️ **绝对不要** 把 API 密钥提交到 Git 仓库！`.env` 已经在 `.gitignore` 中排除了。

### 3.5 下载 Embedding 模型

```bash
# 如果用 Git 方式部署，模型文件不会包含在内（被 gitignore 了）
# 需要手动下载 bge-small-zh-v1.5
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-small-zh-v1.5')"
```

---

## 第四步：测试运行

```bash
# 先手动测试，确保能正常启动
cd /opt/ai-teaching-agent
source venv/bin/activate
cd backend_python
python api_server.py
```

在本机浏览器访问 `http://服务器IP:8000`（或你的 API 端口），确认能看到响应。

---

## 第五步：配置为系统服务（生产部署）

### 5.1 创建 systemd 服务

```bash
sudo nano /etc/systemd/system/ai-teaching-agent.service
```

写入以下内容：

```ini
[Unit]
Description=AI Teaching Agent - FastAPI Backend
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/ai-teaching-agent/backend_python
Environment="PATH=/opt/ai-teaching-agent/venv/bin"
EnvironmentFile=/opt/ai-teaching-agent/.env
ExecStart=/opt/ai-teaching-agent/venv/bin/uvicorn api_server:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 5.2 启动并设置开机自启

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-teaching-agent
sudo systemctl start ai-teaching-agent

# 查看状态
sudo systemctl status ai-teaching-agent

# 查看日志
sudo journalctl -u ai-teaching-agent -f
```

---

## 第六步：配置 Nginx 反向代理

### 6.1 配置 Nginx

```bash
sudo nano /etc/nginx/sites-available/ai-teaching-agent
```

```nginx
server {
    listen 80;
    server_name 你的域名或IP;

    # 前端静态文件
    location / {
        root /opt/ai-teaching-agent/frontend_web;
        index index.html;
        try_files $uri $uri/ /index.html;
    }

    # 后端 API 代理
    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 300s;  # AI 生成可能较慢
    }

    # PPT/文件下载
    location /ppts/ {
        alias /opt/ai-teaching-agent/ppts/;
    }

    # 图片资源
    location /images/ {
        alias /opt/ai-teaching-agent/backend_python/images/;
    }
}
```

### 6.2 启用配置

```bash
sudo ln -s /etc/nginx/sites-available/ai-teaching-agent /etc/nginx/sites-enabled/
sudo nginx -t           # 测试配置
sudo systemctl reload nginx
```

---

## 第七步：配置防火墙

```bash
# Ubuntu (ufw)
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS（如果后续配 SSL）
sudo ufw enable

# CentOS (firewalld)
sudo firewall-cmd --permanent --add-service=ssh
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

---

## 第八步：配置 HTTPS（可选但强烈推荐）

```bash
# 安装 Certbot
sudo apt install -y certbot python3-certbot-nginx

# 自动配置 SSL（需要先将域名解析到服务器IP）
sudo certbot --nginx -d 你的域名.com

# 自动续期测试
sudo certbot renew --dry-run
```

---

## 日常运维命令速查

| 操作 | 命令 |
|------|------|
| SSH 登录 | `ssh myserver` |
| 查看服务状态 | `sudo systemctl status ai-teaching-agent` |
| 重启服务 | `sudo systemctl restart ai-teaching-agent` |
| 查看实时日志 | `sudo journalctl -u ai-teaching-agent -f` |
| 更新代码 | `cd /opt/ai-teaching-agent && git pull && sudo systemctl restart ai-teaching-agent` |
| 更新依赖 | `source venv/bin/activate && pip install -r requirements.txt` |
