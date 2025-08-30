# 🤖 UnforgettableEvilBot - WhatsApp AI Digest System
A sophisticated WhatsApp chat monitoring system that uses AI to analyze messages, create intelligent digests, and deliver them to Telegram channels. Built with FastAPI, Node.js, and OpenAI integration.
## ✨ Features
### 🔐 Authentication & User Management
- **Multi-user system** with secure authentication
- **Admin panel** for user management and system monitoring
- **JWT-based authentication** with configurable expiration
- **Role-based access control**
### 📱 WhatsApp Integration
- **Real-time WhatsApp Web connection** using Puppeteer
- **Persistent sessions** that survive container restarts
- **Automatic reconnection** on connection loss
- **Multi-user WhatsApp support** with session isolation
- **Webhook-based message processing** for real-time updates
### 🤖 AI-Powered Analysis
- **OpenAI GPT-4 integration** for message importance analysis
- **Intelligent digest generation** with context awareness
- **Configurable AI parameters** (temperature, max tokens, model)
- **Message categorization** and priority scoring
### 📊 Digest Management
- **Automated digest scheduling** with configurable intervals
- **Customizable digest formats** and delivery times
- **Multiple digest types** (daily, weekly, urgent)
- **Rich formatting** with message context and metadata
### 📨 Telegram Integration
- **Direct Telegram channel delivery**
- **Rich message formatting** with markdown support
- **Delivery status tracking**
- **Test connection functionality**
### 🏗️ System Architecture
- **Microservices architecture** with Python backend and Node.js bridge
- **PostgreSQL database** with SQLAlchemy ORM
- **Redis caching** for performance optimization
- **Docker containerization** for easy deployment
- **Health monitoring** and system metrics
### 🔧 Advanced Features
- **Rate limiting** and request throttling
- **Circuit breaker pattern** for external API calls
- **Comprehensive logging** with structured output
- **Performance monitoring** and metrics collection
- **Database optimization** and cleanup routines
- **Background task processing** with async support
## 🚀 Quick Start
### Prerequisites
- **Python 3.11+**
- **Node.js 18+**
- **PostgreSQL 13+**
- **Redis 6+** (optional but recommended)
- **Docker & Docker Compose** (for containerized deployment)
### Option 1: Docker Deployment (Recommended)
1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd UnforgettableEvilBot
   ```
2. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```
3. **Start the system**
   ```bash
   docker-compose up -d
   ```
4. **Access the application**
   - **API**: http://localhost:9876
- **Admin Panel**: http://localhost:9876/admin/login
- **API Documentation**: http://localhost:9876/docs
### Option 2: Local Development
1. **Install Python dependencies**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
2. **Install Node.js dependencies**
   ```bash
   cd whatsapp_bridge
   npm install
   cd ..
   ```
3. **Set up database**
   ```bash
   # Create PostgreSQL database
   createdb unforgettable_evil_bot
   # Run migrations
   alembic upgrade head
   ```
4. **Configure environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```
5. **Start the application**
   ```bash
   # Terminal 1: Start Python backend
   uvicorn main:app --reload --host 0.0.0.0 --port 9876
   # Terminal 2: Start WhatsApp bridge
   cd whatsapp_bridge
   node bridge.js
   ```
## ⚙️ Configuration
### Required Environment Variables
```bash
# Database
DATABASE_URL=postgresql://user:password@localhost/unforgettable_evil_bot
# Security
SECRET_KEY=your-super-secret-key-here
ADMIN_PASSWORD=your-admin-password
# OpenAI
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o-mini
OPENAI_MAX_TOKENS=1000
OPENAI_TEMPERATURE=0.3
# Telegram
TELEGRAM_BOT_TOKEN=your-telegram-bot-token
# Redis (optional)
REDIS_URL=redis://localhost:6379/0
REDIS_ENABLED=true
```
### Optional Configuration
```bash
# Performance
MAX_WORKERS=10
DB_POOL_SIZE=20
CACHE_TTL_DEFAULT=3600
# Data retention
CLEANUP_OLD_MESSAGES_DAYS=30
CLEANUP_OLD_SYSTEM_LOGS_DAYS=7
# WhatsApp
WHATSAPP_SESSION_PATH=./whatsapp_sessions
```
## 📚 API Documentation
### Authentication Endpoints
- `POST /auth/register` - User registration
- `POST /auth/login` - User login
- `GET /auth/me` - Get current user info
### User Management
- `GET /users/me` - Current user information
- `PUT /users/settings` - Update user settings
- `GET /users/chats` - List monitored chats
- `POST /users/chats` - Add chat for monitoring
- `DELETE /users/chats/{chat_id}` - Remove chat from monitoring
### WhatsApp Integration
- `POST /whatsapp/connect` - Connect to WhatsApp
- `GET /whatsapp/chats/available` - Get available chats
- `POST /whatsapp/disconnect` - Disconnect from WhatsApp
- `POST /whatsapp/telegram/test` - Test Telegram connection
- `POST /webhook/whatsapp/message` - WhatsApp webhook endpoint
### Admin Panel
- `GET /admin/login` - Admin login page
- `GET /admin/users` - User management
- `GET /admin/dashboard` - System dashboard
### System Health
- `GET /health` - System health check
- `GET /metrics` - System metrics
- `GET /logs` - System logs
## 🏗️ Architecture Overview
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   WhatsApp      │───▶│   Node.js       │───▶│   Python        │
│   Web           │    │   Bridge        │    │   FastAPI       │
│   (Puppeteer)   │    │   (Port 3000)   │    │   (Port 9876)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │                        │
                              ▼                        ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Telegram      │◀───│   PostgreSQL    │◀───│   OpenAI        │
│   Bot           │    │   Database      │    │   API           │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌─────────────────┐
                       │   Redis Cache   │
                       └─────────────────┘
```
## 🔧 Development
### Project Structure
```
UnforgettableEvilBot/
├── app/                    # Python application
│   ├── api/               # API endpoints
│   ├── auth/              # Authentication
│   ├── core/              # Core services
│   ├── database/          # Database models
│   ├── models/            # Data models
│   ├── scheduler/         # Background tasks
│   ├── telegram/          # Telegram integration
│   └── whatsapp/          # WhatsApp services
├── whatsapp_bridge/       # Node.js WhatsApp bridge
├── config/                # Configuration
├── tests/                 # Test suite
├── web/                   # Web templates
└── docker/                # Docker configuration
```
### Running Tests
```bash
# Activate virtual environment
source .venv/bin/activate
# Run all tests
pytest
# Run with coverage
pytest --cov=app --cov-report=html
# Run specific test categories
pytest tests/unit/
pytest tests/integration/
```
### Code Quality
```bash
# Format code
black app/ tests/
# Lint code
flake8 app/ tests/
# Type checking
mypy app/
# Sort imports
isort app/ tests/
```
## 📊 Monitoring & Logs
### Health Checks
- **Application health**: `GET /health`
- **Database health**: Automatic monitoring
- **WhatsApp connection**: Real-time status tracking
- **Telegram bot**: Connection verification
### Logging
- **Structured logging** with JSON format
- **Request tracing** for debugging
- **Performance metrics** collection
- **Error tracking** and alerting
### Metrics
- **Request rates** and response times
- **Database performance** metrics
- **WhatsApp connection** statistics
- **AI API usage** and costs
## 🚀 Deployment
### Production Deployment
See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed production deployment instructions.
### Docker Compose
```bash
# Production deployment
docker-compose -f docker-compose.yml up -d
# Development deployment
docker-compose -f docker-compose.dev.yml up -d
# Coolify deployment
docker-compose -f docker-compose.coolify.yml up -d
```
### Environment Variables
- Copy `.env.example` to `.env`
- Configure all required variables
- Use strong passwords and API keys
- Enable SSL in production
## 🤝 Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run the test suite
6. Submit a pull request
## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
## 🆘 Support
- **Documentation**: Check the [docs/](docs/) directory
- **Issues**: Report bugs on GitHub Issues
- **Discussions**: Use GitHub Discussions for questions
- **Deployment**: See [DEPLOYMENT.md](DEPLOYMENT.md)
## 🔄 Changelog
### v1.0.0 (Current)
- ✅ Complete WhatsApp integration with Puppeteer
- ✅ AI-powered message analysis
- ✅ Automated digest generation
- ✅ Telegram delivery system
- ✅ Admin panel and user management
- ✅ Docker containerization
- ✅ Production-ready deployment
- ✅ Comprehensive monitoring and logging
