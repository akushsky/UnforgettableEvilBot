#!/bin/bash

# Test runner script for pre-commit hook
# This script runs all tests and provides clear feedback

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Running tests before commit...${NC}"

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo -e "${RED}Error: Virtual environment not found. Please run 'python -m venv .venv' and activate it.${NC}"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Check if pytest is installed
if ! python -c "import pytest" 2>/dev/null; then
    echo -e "${RED}Error: pytest not found. Please install it with 'pip install pytest'.${NC}"
    exit 1
fi

# Run tests with coverage
echo -e "${YELLOW}Running test suite...${NC}"
if python -m pytest --tb=short -q --cov=app --cov-report=term-missing tests/; then
    echo -e "${GREEN}✅ All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}❌ Tests failed! Please fix the failing tests before committing.${NC}"
    echo -e "${YELLOW}To run tests manually: python -m pytest${NC}"
    exit 1
fi
