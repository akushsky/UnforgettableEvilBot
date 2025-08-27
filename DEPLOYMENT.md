# 🚀 WhatsApp Digest System Deployment Guide

## 📋 Table of Contents

- [System Requirements](#system-requirements)
- [Environment Preparation](#environment-preparation)
- [Local Deployment](#local-deployment)
- [Docker Deployment](#docker-deployment)
- [Production Deployment](#production-deployment)
- [Monitoring and Logs](#monitoring-and-logs)
- [Maintenance](#maintenance)

---

## 💻 System Requirements

### Minimum Requirements:
- **CPU**: 2 cores
- **RAM**: 4 GB
- **Disk**: 20 GB SSD
- **OS**: Ubuntu 20.04+ / CentOS 8+ / macOS 10.15+

### Recommended Requirements:
- **CPU**: 4 cores
- **RAM**: 8 GB
- **Disk**: 50 GB SSD
- **OS**: Ubuntu 22.04 LTS

### External Dependencies:
- **PostgreSQL**: 13+
- **Redis**: 6+ (optional)
- **Node.js**: 18+ (for WhatsApp bridge)
- **Python**: 3.11+

---

## 🛠 Environment Preparation

### 1. Installing System Dependencies

#### Ubuntu/Debian:
```bash
# System update
sudo apt update && sudo apt upgrade -y

# Install Python and dependencies
sudo apt install -y python3.11 python3.11-venv python3.11-dev
sudo apt install -y postgresql postgresql-contrib redis-server
sudo apt install -y nodejs npm git curl

# Install Docker (optional)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
```

#### CentOS/RHEL:
```bash
# Install EPEL repository
sudo dnf install -y epel-release

# Install dependencies
sudo dnf install -y python3.11 python3.11-pip python3.11-devel
sudo dnf install -y postgresql postgresql-server redis
sudo dnf module install -y nodejs:18/common
```

### 2. Database Setup

#### PostgreSQL:
```bash
# Initialize PostgreSQL (CentOS only)
sudo postgresql-setup --initdb
sudo systemctl enable postgresql
sudo systemctl start postgresql

# Create user and database
sudo -u postgres psql

CREATE USER whatsapp_digest WITH PASSWORD 'secure_password';
CREATE DATABASE whatsapp_digest OWNER whatsapp_digest;
GRANT ALL PRIVILEGES ON DATABASE whatsapp_digest TO whatsapp_digest;
\q
```

### 3. Environment Variables Setup

Create `.env` file:
```bash
# Database
DATABASE_URL=postgresql://whatsapp_digest:secure_password@localhost/whatsapp_digest

# Security
SECRET_KEY=your-super-secret-key-here-change-it
JWT_SECRET_KEY=another-secret-key-for-jwt

# OpenAI
OPENAI_API_KEY=your-openai-api-key

# Telegram
TELEGRAM_BOT_TOKEN=your-telegram-bot-token

# WhatsApp Bridge
WHATSAPP_SESSION_PATH=/opt/whatsapp-digest/sessions

# Redis (optional)
REDIS_URL=redis://localhost:6379/0

# Logs
LOG_LEVEL=INFO
LOG_FILE_PATH=/var/log/whatsapp-digest/app.log

# Performance
MAX_WORKERS=4
CACHE_TTL_DEFAULT=300
```

---

## 🏠 Local Deployment

### 1. Cloning the Repository
```bash
git clone https://github.com/whatsapp-digest/bot.git
cd whatsapp-digest-bot
```

### 2. Creating a Virtual Environment
```bash
python3.11 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or .venv\Scripts\activate  # Windows
```

### 3. Installing Dependencies
```bash
pip install -r requirements.txt

# For development (includes linters and tests)
pip install -e ".[dev]"
```

### 4. Database Migrations
```bash
# Initialize Alembic (if needed)
alembic init alembic

# Apply migrations
alembic upgrade head

# Or create tables directly
python setup_database.py
```

### 5. Running the Application
```bash
# Deployment for development
python start_local.py

# Or directly via uvicorn
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### 6. Setting Up WhatsApp Bridge
```bash
cd whatsapp_bridge
npm install
node persistent_bridge.js
```

---

## 🐳 Docker Deployment

### 1. Using a Pre-built Image
```bash
# Simple run
docker run -d \
  --name whatsapp-digest \
  -p 8000:8000 \
  -e DATABASE_URL=postgresql://user:pass@host/db \
  -e OPENAI_API_KEY=your-key \
  whatsapp-digest:latest
```

### 2. Docker Compose (recommended)
```bash
# Run all services
docker-compose up -d

# Only the main application
docker-compose up -d app

# With PostgreSQL and Redis
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

### 3. docker-compose.yml Configuration
```yaml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://postgres:password@db:5432/whatsapp_digest
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - ./logs:/app/logs
      - ./whatsapp_sessions:/app/whatsapp_sessions

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: whatsapp_digest
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
```

---

## 🏭 Production Deployment

### 1. Server Setup

#### Creating System User:
```bash
sudo useradd -m -s /bin/bash whatsapp-digest
sudo mkdir -p /opt/whatsapp-digest
sudo chown whatsapp-digest:whatsapp-digest /opt/whatsapp-digest
```

#### Creating Directories:
```bash
sudo mkdir -p /var/log/whatsapp-digest
sudo mkdir -p /etc/whatsapp-digest
sudo chown whatsapp-digest:whatsapp-digest /var/log/whatsapp-digest
sudo chown whatsapp-digest:whatsapp-digest /etc/whatsapp-digest
```

### 2. Systemd Service

Create `/etc/systemd/system/whatsapp-digest.service`:
```ini
[Unit]
Description=WhatsApp Digest System
After=network.target postgresql.service redis.service
Wants=postgresql.service redis.service

[Service]
Type=exec
User=whatsapp-digest
Group=whatsapp-digest
WorkingDirectory=/opt/whatsapp-digest
Environment=PATH=/opt/whatsapp-digest/.venv/bin
ExecStart=/opt/whatsapp-digest/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
ExecReload=/bin/kill -HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3. Nginx Configuration

Create `/etc/nginx/sites-available/whatsapp-digest`:
```nginx
server {
    listen 80;
    server_name your-domain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL Configuration
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512;
    ssl_prefer_server_ciphers off;

    # Security Headers
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";
    add_header Strict-Transport-Security "max-age=31536000" always;

    # Main application
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # Static files
    location /static/ {
        alias /opt/whatsapp-digest/web/static/;
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Monitoring dashboard
    location /monitoring/dashboard {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Prometheus metrics (restrict access)
    location /metrics {
        allow 127.0.0.1;
        allow 10.0.0.0/8;
        deny all;
        proxy_pass http://127.0.0.1:8000;
    }
}
```

### 4. SSL Certificate (Let's Encrypt)
```bash
# Install Certbot
sudo apt install certbot python3-certbot-nginx

# Get certificate
sudo certbot --nginx -d your-domain.com

# Auto-renewal
sudo crontab -e
# Add: 0 12 * * * /usr/bin/certbot renew --quiet
```

### 5. Starting Services
```bash
# Enable and start service
sudo systemctl enable whatsapp-digest
sudo systemctl start whatsapp-digest

# Check status
sudo systemctl status whatsapp-digest

# Reload Nginx
sudo systemctl reload nginx
```

---

## 📊 Monitoring and Logs

### 1. Prometheus Monitoring

#### Installing Prometheus:
```bash
# Create user
sudo useradd --no-create-home --shell /bin/false prometheus

# Download Prometheus
wget https://github.com/prometheus/prometheus/releases/download/v2.40.0/prometheus-2.40.0.linux-amd64.tar.gz
tar xvf prometheus-2.40.0.linux-amd64.tar.gz
sudo cp prometheus-2.40.0.linux-amd64/prometheus /usr/local/bin/
sudo cp prometheus-2.40.0.linux-amd64/promtool /usr/local/bin/
sudo chown prometheus:prometheus /usr/local/bin/prometheus
sudo chown prometheus:prometheus /usr/local/bin/promtool

# Create configuration
sudo mkdir /etc/prometheus
sudo mkdir /var/lib/prometheus
sudo chown prometheus:prometheus /etc/prometheus
sudo chown prometheus:prometheus /var/lib/prometheus
```

#### Prometheus Configuration (`/etc/prometheus/prometheus.yml`):
```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'whatsapp-digest'
    static_configs:
      - targets: ['localhost:9090']
    scrape_interval: 5s
    metrics_path: /metrics

  - job_name: 'whatsapp-digest-app'
    static_configs:
      - targets: ['localhost:8000']
    scrape_interval: 15s
    metrics_path: /metrics
```

### 2. Logrotate Configuration

Create `/etc/logrotate.d/whatsapp-digest`:
```
/var/log/whatsapp-digest/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    copytruncate
    postrotate
        systemctl reload whatsapp-digest
    endscript
}
```

### 3. Alert Systems

#### Setting up in the application:
```python
# Alerts are already configured in main.py
# Check via: GET /monitoring/alerts

# Manual health check:
curl -X POST http://localhost:8000/monitoring/health-check
```

---

## 🔧 Maintenance

### 1. Backup

#### Backup Script:
```bash
#!/bin/bash
# /opt/whatsapp-digest/backup.sh

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backup/whatsapp-digest"
DB_NAME="whatsapp_digest"
DB_USER="whatsapp_digest"

# Create directory
mkdir -p $BACKUP_DIR

# Database backup
pg_dump -h localhost -U $DB_USER $DB_NAME | gzip > $BACKUP_DIR/db_backup_$DATE.sql.gz

# Configuration backup
tar -czf $BACKUP_DIR/config_backup_$DATE.tar.gz /etc/whatsapp-digest/ /opt/whatsapp-digest/.env

# WhatsApp sessions backup
tar -czf $BACKUP_DIR/sessions_backup_$DATE.tar.gz /opt/whatsapp-digest/whatsapp_sessions/

# Clean up old backups (older than 30 days)
find $BACKUP_DIR -name "*.gz" -mtime +30 -delete

echo "Backup completed: $DATE"
```

#### Cron Setup:
```bash
# Daily backup at 2:00
0 2 * * * /opt/whatsapp-digest/backup.sh >> /var/log/whatsapp-digest/backup.log 2>&1
```

### 2. System Update

#### Update Script:
```bash
#!/bin/bash
# /opt/whatsapp-digest/update.sh

echo "Starting update process..."

# Stop service
sudo systemctl stop whatsapp-digest

# Backup
/opt/whatsapp-digest/backup.sh

# Update code
cd /opt/whatsapp-digest
git pull origin main

# Update dependencies
.venv/bin/pip install -r requirements.txt

# Database migrations
.venv/bin/alembic upgrade head

# Start service
sudo systemctl start whatsapp-digest

# Check status
sleep 5
sudo systemctl status whatsapp-digest

echo "Update completed!"
```

### 3. Diagnostics

#### Checking System Health:
```bash
# Service status
sudo systemctl status whatsapp-digest

# Application logs
sudo journalctl -u whatsapp-digest -f

# API check
curl http://localhost:8000/health

# Metrics
curl http://localhost:8000/metrics

# Monitoring dashboard
curl http://localhost:8000/monitoring/dashboard
```

#### Common Issues:

1. **Service does not start**:
   - Check environment variables
   - Ensure database is accessible
   - Check file permissions

2. **WhatsApp does not connect**:
   - Check Node.js bridge
   - Clear sessions directory
   - Restart bridge

3. **High memory usage**:
   - Check number of workers
   - Configure pool_size for database
   - Clear old logs

---

## 📞 Support

- **Documentation**: [GitHub Wiki](https://github.com/whatsapp-digest/bot/wiki)
- **Issues**: [GitHub Issues](https://github.com/whatsapp-digest/bot/issues)
- **Email**: team@whatsappdigest.com

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.
