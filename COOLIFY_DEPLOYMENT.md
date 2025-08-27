# 🚀 Coolify Deployment Guide

## Overview

This guide will help you deploy the WhatsApp Digest System to Coolify, a modern self-hosted PaaS platform.

## ✅ System Compatibility

**Yes, the system is fully compatible with Coolify!** Here's why:

### ✅ **Docker Support**
- Multi-stage Dockerfile with Python 3.12
- Optimized for production deployment
- Health checks and proper signal handling

### ✅ **Environment Variables**
- All configuration via environment variables
- No hardcoded values
- Coolify-friendly variable structure

### ✅ **Database Support**
- PostgreSQL support (Coolify can provision)
- Redis support for caching
- Migration system with Alembic

### ✅ **Resource Management**
- Resource limits configured
- Memory and CPU constraints
- Proper volume management

## 🎯 Deployment Steps

### 1. **Prepare Your Repository**

Ensure your repository is ready:
```bash
# Clone your repository
git clone <your-repo-url>
cd UnforgettableEvilBot

# Verify Dockerfile exists
ls Dockerfile

# Verify docker-compose.coolify.yml exists
ls docker-compose.coolify.yml
```

### 2. **Coolify Setup**

1. **Access Coolify Dashboard**
   - Navigate to your Coolify instance
   - Go to "Applications" → "New Application"

2. **Create New Application**
   - **Name**: `whatsapp-digest`
   - **Repository**: Select your GitHub/GitLab repo
   - **Branch**: `main` (or your preferred branch)
   - **Build Pack**: `Docker`

3. **Configure Build Settings**
   - **Dockerfile Path**: `Dockerfile`
   - **Docker Compose**: Use `docker-compose.coolify.yml`
   - **Port**: `8000` (FastAPI)

### 3. **Environment Variables**

Set these required environment variables in Coolify:

#### **Required API Keys**
```bash
OPENAI_API_KEY=your-openai-api-key-here
TELEGRAM_BOT_TOKEN=your-telegram-bot-token-here
SECRET_KEY=your-super-secret-key-here
ADMIN_PASSWORD=your-secure-admin-password-here
```

#### **Database Configuration**
```bash
# Coolify will provide these if you use their database service
DATABASE_URL=postgresql://user:password@host:port/database
REDIS_URL=redis://host:port/0
```

#### **Optional Settings**
```bash
# Performance tuning
MAX_WORKERS=10
MAX_PROCESS_WORKERS=4
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=30

# Cleanup settings
CLEANUP_OLD_MESSAGES_DAYS=30
CLEANUP_OLD_SYSTEM_LOGS_DAYS=7

# OpenAI settings
OPENAI_MODEL=gpt-4o-mini
OPENAI_MAX_TOKENS=1000
OPENAI_TEMPERATURE=0.3

# Repository optimization
USE_OPTIMIZED_REPOSITORIES=true
```

### 4. **Database Setup**

#### **Option A: Use Coolify Database Service**
1. Create PostgreSQL database in Coolify
2. Create Redis instance in Coolify
3. Coolify will automatically provide `DATABASE_URL` and `REDIS_URL`

#### **Option B: External Database**
1. Use your own PostgreSQL/Redis instances
2. Manually set `DATABASE_URL` and `REDIS_URL` environment variables

### 5. **Deploy**

1. **Build and Deploy**
   - Click "Deploy" in Coolify
   - Monitor the build process
   - Check logs for any issues

2. **Verify Deployment**
   - Health check should pass: `http://your-domain/health`
   - API docs available: `http://your-domain/docs`
   - Admin panel: `http://your-domain/admin`

## 🔧 Configuration Details

### **Resource Limits**
The system is configured with reasonable limits:
- **Memory**: 2GB max, 512MB reserved
- **CPU**: 1 core max, 0.5 core reserved
- **Storage**: Persistent volumes for sessions and logs

### **Health Checks**
- **Endpoint**: `/health`
- **Interval**: 30 seconds
- **Timeout**: 10 seconds
- **Retries**: 3 attempts

### **Ports**
- **8000**: FastAPI application
- **3000**: WhatsApp Bridge (internal)

## 📊 Monitoring

### **Built-in Monitoring**
- Health check endpoint: `/health`
- Metrics endpoint: `/metrics`
- Monitoring dashboard: `/monitoring/dashboard`

### **Coolify Monitoring**
- Resource usage (CPU, Memory, Disk)
- Container logs
- Application status

## 🔄 Updates and Maintenance

### **Automatic Updates**
1. Push changes to your repository
2. Coolify will automatically rebuild and deploy
3. Zero-downtime deployments

### **Manual Updates**
1. Go to Coolify dashboard
2. Select your application
3. Click "Redeploy"

### **Database Migrations**
- Migrations run automatically on startup
- No manual intervention required
- Safe rollback support

## 🚨 Troubleshooting

### **Common Issues**

1. **Build Fails**
   ```bash
   # Check Dockerfile syntax
   docker build -t test .

   # Verify requirements.txt
   pip install -r requirements.txt
   ```

2. **Health Check Fails**
   ```bash
   # Check application logs
   curl http://your-domain/health

   # Verify environment variables
   # Check database connectivity
   ```

3. **WhatsApp Bridge Issues**
   ```bash
   # Check bridge logs
   # Verify Node.js dependencies
   # Check Chrome installation
   ```

### **Logs and Debugging**
- **Application Logs**: Available in Coolify dashboard
- **Container Logs**: `docker logs <container-id>`
- **Health Check**: `curl http://your-domain/health`

## 🎯 Production Checklist

### **Before Deployment**
- [ ] All environment variables set
- [ ] Database and Redis configured
- [ ] API keys secured
- [ ] Resource limits appropriate

### **After Deployment**
- [ ] Health check passes
- [ ] API documentation accessible
- [ ] Database migrations completed
- [ ] WhatsApp Bridge running
- [ ] Monitoring dashboard working

### **Security Considerations**
- [ ] Use HTTPS (Coolify handles this)
- [ ] Secure API keys
- [ ] Database access restricted
- [ ] Regular backups configured

## 🚀 Performance Optimization

### **For High Traffic**
```bash
# Increase worker processes
MAX_WORKERS=20
MAX_PROCESS_WORKERS=8

# Optimize database
DB_POOL_SIZE=40
DB_MAX_OVERFLOW=60

# Enable caching
USE_OPTIMIZED_REPOSITORIES=true
REDIS_ENABLED=true
```

### **For Low Traffic**
```bash
# Reduce resource usage
MAX_WORKERS=5
MAX_PROCESS_WORKERS=2
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
```

## 📞 Support

- **Coolify Documentation**: [https://coolify.io/docs](https://coolify.io/docs)
- **Application Issues**: Check GitHub issues
- **Deployment Problems**: Review this guide and logs

---

**🎉 Your WhatsApp Digest System is now ready for production deployment on Coolify!**
