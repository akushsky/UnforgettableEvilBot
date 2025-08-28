#!/bin/bash

# Test runner script for the WhatsApp Digest Bot
# This script runs tests with proper configuration and environment setup

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default to all tests (unit + integration)
TEST_TYPE=${1:-all}

echo -e "${GREEN}🧪 Running tests for WhatsApp Digest Bot${NC}"
echo -e "${YELLOW}Test type: ${TEST_TYPE}${NC}"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}❌ Virtual environment not found. Please run 'python -m venv .venv' first.${NC}"
    exit 1
fi

# Activate virtual environment
echo -e "${YELLOW}📦 Activating virtual environment...${NC}"
source .venv/bin/activate

# Install/upgrade test dependencies
echo -e "${YELLOW}📦 Installing test dependencies...${NC}"
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-cov pytest-mock

# Set test environment file
export TEST_ENV_FILE=".env.test"

# Run tests based on type
if [ "$TEST_TYPE" = "unit" ]; then
    echo -e "${GREEN}🔬 Running unit tests...${NC}"
    python -m pytest tests/unit/ -v --tb=short --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml
elif [ "$TEST_TYPE" = "integration" ]; then
    echo -e "${GREEN}🔗 Running integration tests...${NC}"
    echo -e "${YELLOW}ℹ️  Starting PostgreSQL test database with Docker...${NC}"

    # Start test database with fresh data
    ./scripts/manage_test_db.sh cleanup
    ./scripts/manage_test_db.sh start

    # Run integration tests with cleanup on exit
    trap './scripts/manage_test_db.sh stop' EXIT
    python -m pytest tests/integration/ -v --tb=short --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml

elif [ "$TEST_TYPE" = "all" ]; then
    echo -e "${GREEN}🔬 Running all tests...${NC}"
    echo -e "${YELLOW}ℹ️  Starting PostgreSQL test database with Docker for integration tests...${NC}"

    # Start test database with fresh data
    ./scripts/manage_test_db.sh cleanup
    ./scripts/manage_test_db.sh start

    # Run all tests with cleanup on exit
    trap './scripts/manage_test_db.sh stop' EXIT
    python -m pytest tests/ -v --tb=short --cov=app --cov-report=term-missing --cov-report=html:htmlcov --cov-report=xml
else
    echo -e "${RED}❌ Invalid test type. Use 'unit', 'integration', or 'all'${NC}"
    echo -e "${YELLOW}Usage: $0 [unit|integration|all]${NC}"
    echo -e "${YELLOW}Default: unit tests only${NC}"
    exit 1
fi

# Check if tests passed
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    echo -e "${GREEN}📊 Coverage report generated in htmlcov/index.html${NC}"
else
    echo -e "${RED}❌ Tests failed! Please fix the failing tests before committing.${NC}"
    echo -e "${YELLOW}To run tests manually: python -m pytest${NC}"
    exit 1
fi
