# WhatsApp Digest System

A WhatsApp chat monitoring system that creates digests using OpenAI and sends them to Telegram.

## Features

- ✅ User registration and authentication
- ✅ WhatsApp connection (stub)
- ✅ Selected chat monitoring
- ✅ Message importance analysis via OpenAI
- ✅ Digest creation
- ✅ Telegram channel delivery
- ✅ Configurable update intervals

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy `.env.example` to `.env` and fill in the required variables:

```bash
cp .env.example .env
```

Make sure to specify:
- `OPENAI_API_KEY` - your OpenAI API key
- `TELEGRAM_BOT_TOKEN` - Telegram bot token
- `SECRET_KEY` - secret key for JWT tokens

### 3. Create Database

```bash
alembic upgrade head
```

### 4. Start Application

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

API will be available at: http://localhost:8000

Swagger documentation: http://localhost:8000/docs

## API Endpoints

### Authentication
- `POST /auth/register` - User registration
- `POST /auth/login` - Login to system

### Users
- `GET /users/me` - Current user information
- `POST /users/settings/digest` - Digest settings
- `GET /users/chats` - List of monitored chats
- `POST /users/chats` - Add chat for monitoring
- `DELETE /users/chats/{chat_id}` - Remove chat from monitoring

### WhatsApp
- `POST /whatsapp/connect` - Connect to WhatsApp
- `GET /whatsapp/chats/available` - Get available chats
- `POST /whatsapp/disconnect` - Disconnect from WhatsApp
- `POST /whatsapp/telegram/test` - Test Telegram connection

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   WhatsApp      │───▶│   FastAPI       │───▶│   OpenAI        │
│   Integration   │    │   Backend       │    │   Analysis      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                              │
                              ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Telegram      │◀───│   SQLite DB     │───▶│   Scheduler     │
│   Bot           │    │   (Users,Chats, │    │   (Background   │
└─────────────────┘    │   Messages)     │    │   Tasks)        │
                       └─────────────────┘    └─────────────────┘
```

## Usage Example

1. Register through the API
2. Connect your WhatsApp account
3. Select chats for monitoring
4. Configure Telegram channel
5. System will automatically create digests

## TODO

- [ ] Real integration with whatsapp-web.js
- [ ] Web interface for management
- [ ] Multi-language support
- [ ] Advanced filtering settings
