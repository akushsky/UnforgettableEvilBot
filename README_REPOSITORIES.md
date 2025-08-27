# Repository Selection System

## Overview

The system now has a **configuration-based repository selection mechanism** that allows you to choose between basic and optimized repositories based on your environment and performance needs.

## How It Works

### 1. Configuration Setting

Add this environment variable to control repository selection:

```bash
# Use optimized repositories (with caching, batch operations, etc.)
USE_OPTIMIZED_REPOSITORIES=true

# Use basic repositories (default)
USE_OPTIMIZED_REPOSITORIES=false
```

### 2. Repository Factory

The system uses a factory pattern to automatically select the appropriate repository:

```python
from app.core.repository_factory import repository_factory

# Get the appropriate repository based on configuration
user_repo = repository_factory.get_user_repository()
message_repo = repository_factory.get_whatsapp_message_repository()
digest_repo = repository_factory.get_digest_log_repository()
```

### 3. Repository Types

#### Basic Repositories (`repositories.py`)
- **Simple CRUD operations**
- **No caching**
- **Direct database queries**
- **Lower memory usage**
- **Suitable for development and low-traffic scenarios**

#### Optimized Repositories (`optimized_repositories.py`)
- **Redis caching with TTL**
- **Batch operations**
- **Database cleanup methods**
- **Statistics and analytics**
- **Higher performance for production**
- **More memory usage due to caching**

## Usage Examples

### Before (Manual Selection)
```python
# Had to manually choose which repository to import
from app.core.repositories import user_repository
# OR
from app.core.optimized_repositories import optimized_user_repository
```

### After (Automatic Selection)
```python
from app.core.repository_factory import repository_factory

# Automatically gets the right repository based on USE_OPTIMIZED_REPOSITORIES setting
user_repo = repository_factory.get_user_repository()
users = user_repo.get_all(db, skip=0, limit=100)
```

## Migration Status

### ✅ Completed
- **User API** (`app/api/users.py`) - Now uses factory pattern
- **Repository Factory** - Created and functional
- **Configuration** - Added `USE_OPTIMIZED_REPOSITORIES` setting

### 🔄 In Progress
- **WhatsApp Webhooks** - Still using direct queries
- **Digest Scheduler** - Still using direct queries
- **Other services** - Need migration to factory pattern

### 📋 To Do
1. Migrate WhatsApp webhook handlers to use repositories
2. Migrate digest scheduler to use repositories
3. Add optimized version for `MonitoredChatRepository`
4. Add performance monitoring for repository usage

## Performance Comparison

| Scenario | Basic Repositories | Optimized Repositories |
|----------|-------------------|----------------------|
| **Development** | ✅ Fast enough | ⚠️ Overkill |
| **Low Traffic** | ✅ Good | ✅ Better |
| **High Traffic** | ❌ Slow | ✅ Excellent |
| **Memory Usage** | ✅ Low | ⚠️ Higher |
| **Setup Complexity** | ✅ Simple | ⚠️ Requires Redis |

## Recommendations

### Development Environment
```bash
USE_OPTIMIZED_REPOSITORIES=false
```

### Production Environment
```bash
USE_OPTIMIZED_REPOSITORIES=true
```

### Staging Environment
```bash
# Test both configurations
USE_OPTIMIZED_REPOSITORIES=true  # Test performance
USE_OPTIMIZED_REPOSITORIES=false # Test stability
```

## Benefits

1. **Automatic Selection**: No need to manually choose repositories
2. **Environment Flexibility**: Different configs for different environments
3. **Performance Optimization**: Use optimized repos in production
4. **Development Simplicity**: Use basic repos during development
5. **Gradual Migration**: Can migrate services one by one
6. **Fallback Safety**: If optimized repos fail, can fall back to basic ones
