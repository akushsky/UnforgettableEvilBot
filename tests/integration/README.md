# Integration Tests

This directory contains integration tests that test real database operations and component interactions.

## Overview

Integration tests verify that different components of the system work together correctly with real database connections and actual data persistence.

## Test Structure

### Database Integration Tests (`test_database_integration.py`)

Tests real database operations including:

- **User Management**: Creating, retrieving, updating users
- **Repository Operations**: Testing both basic and optimized repositories
- **Relationship Testing**: User → Chat → Messages relationships
- **Data Integrity**: Constraints, transactions, rollbacks
- **Batch Operations**: Optimized repository batch methods
- **Repository Factory**: Dynamic repository selection

### Test Coverage

The integration tests cover:

1. **User Operations**
   - User creation and retrieval
   - Repository pattern usage
   - Optimized repository features

2. **Chat and Message Operations**
   - Chat creation with relationships
   - Message processing and retrieval
   - Batch operations on messages

3. **Digest and Logging**
   - Digest log creation and retrieval
   - System log operations
   - Period-based queries

4. **Resource Management**
   - Resource savings tracking
   - OpenAI metrics storage
   - Cost calculations

5. **Database Integrity**
   - Constraint validation
   - Transaction rollbacks
   - Data persistence verification

## Running Integration Tests

### Run All Integration Tests
```bash
python -m pytest tests/integration/ -v
```

### Run Specific Test File
```bash
python -m pytest tests/integration/test_database_integration.py -v
```

### Run Specific Test
```bash
python -m pytest tests/integration/test_database_integration.py::TestDatabaseIntegration::test_user_creation_and_retrieval -v
```

## Test Infrastructure

### Fixtures (`conftest.py`)

The integration tests use several fixtures:

- **`db_session`**: Fresh database session for each test
- **`sample_user`**: Pre-created user for testing
- **`sample_chat`**: Pre-created chat for testing
- **`sample_messages`**: Pre-created messages for testing
- **`clean_database`**: Automatic cleanup after each test

### Database Setup

- Uses SQLite in-memory database for fast, isolated testing
- Creates all tables automatically
- Provides fresh session for each test
- Handles transaction rollbacks and cleanup

## Test Categories

### 1. Basic CRUD Operations
Tests fundamental database operations:
- Create, Read, Update, Delete operations
- Data persistence verification
- Relationship integrity

### 2. Repository Pattern Testing
Tests the repository abstraction layer:
- Basic repository operations
- Optimized repository features
- Repository factory functionality

### 3. Data Relationships
Tests complex data relationships:
- User → Chat → Message hierarchies
- Foreign key constraints
- Cascade operations

### 4. Performance Features
Tests optimized repository features:
- Batch operations
- Caching mechanisms
- Query optimization

### 5. Error Handling
Tests error scenarios:
- Constraint violations
- Transaction rollbacks
- Invalid data handling

## Best Practices

### Test Isolation
- Each test runs with a fresh database session
- Automatic cleanup after each test
- No shared state between tests

### Real Data Testing
- Uses actual database models
- Tests real SQL queries
- Verifies data persistence

### Comprehensive Coverage
- Tests both success and failure scenarios
- Covers edge cases and constraints
- Validates business logic

## Future Enhancements

### Planned Integration Tests

1. **API Integration Tests**
   - Real HTTP requests to endpoints
   - Authentication and authorization
   - Request/response validation

2. **External Service Integration**
   - OpenAI API calls
   - Telegram bot interactions
   - WhatsApp bridge testing

3. **Workflow Integration Tests**
   - End-to-end message processing
   - Digest creation workflows
   - User registration flows

4. **Performance Integration Tests**
   - Load testing with real data
   - Database performance under load
   - Cache effectiveness testing

## Troubleshooting

### Common Issues

1. **Database Connection Errors**
   - Ensure SQLite is available
   - Check file permissions
   - Verify database URL configuration

2. **Fixture Errors**
   - Check fixture dependencies
   - Verify fixture scope settings
   - Ensure proper cleanup

3. **Test Isolation Issues**
   - Verify `clean_database` fixture is used
   - Check for shared state between tests
   - Ensure proper session management

### Debugging Tips

1. **Enable SQL Logging**
   ```python
   # In conftest.py
   engine = create_engine("sqlite:///:memory:", echo=True)
   ```

2. **Check Database State**
   ```python
   # In test
   print(f"Users in DB: {db_session.query(User).count()}")
   ```

3. **Verify Data Persistence**
   ```python
   # After operations
   db_session.refresh(user)
   assert user.is_active == False
   ```

## Contributing

When adding new integration tests:

1. **Follow Naming Convention**: `test_*_integration`
2. **Use Appropriate Fixtures**: Leverage existing fixtures when possible
3. **Test Real Scenarios**: Focus on realistic use cases
4. **Include Error Cases**: Test both success and failure paths
5. **Document Complex Tests**: Add comments for complex test logic
