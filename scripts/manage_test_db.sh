#!/bin/bash

# Test Database Management Script
# This script manages a PostgreSQL container for integration tests

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="docker-compose.test.yml"
SERVICE_NAME="postgres-test"
CONTAINER_NAME="whatsapp-digest-test-db"
DB_PORT="5433"
DB_NAME="whatsapp_digest_test"
DB_USER="postgres"
DB_PASSWORD="postgres"

# Function to print colored output
print_status() {
    echo -e "${BLUE}🔧 $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Function to check if Docker is running
check_docker() {
    if ! docker info > /dev/null 2>&1; then
        print_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
}

# Function to check if container is running
is_container_running() {
    docker ps --format "table {{.Names}}" | grep -q "^${CONTAINER_NAME}$"
}

# Function to check if container exists
is_container_exists() {
    docker ps -a --format "table {{.Names}}" | grep -q "^${CONTAINER_NAME}$"
}

# Function to wait for database to be ready
wait_for_db() {
    print_status "Waiting for PostgreSQL to be ready..."

    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if docker exec ${CONTAINER_NAME} pg_isready -U ${DB_USER} -d ${DB_NAME} > /dev/null 2>&1; then
            print_success "PostgreSQL is ready!"
            return 0
        fi

        print_status "Attempt $attempt/$max_attempts: Database not ready yet..."
        sleep 2
        attempt=$((attempt + 1))
    done

    print_error "Database failed to start within expected time"
    return 1
}

# Function to start the test database
start_db() {
    print_status "Starting test PostgreSQL database..."

    if is_container_running; then
        print_warning "Test database is already running"
        return 0
    fi

    # Remove existing container if it exists but is not running
    if is_container_exists; then
        print_status "Removing existing stopped container..."
        docker rm ${CONTAINER_NAME} > /dev/null 2>&1 || true
    fi

    # Start the container
    docker-compose -f ${COMPOSE_FILE} up -d ${SERVICE_NAME}

    # Wait for database to be ready
    wait_for_db

    print_success "Test database started successfully on port ${DB_PORT}"
}

# Function to stop the test database
stop_db() {
    print_status "Stopping test PostgreSQL database..."

    if ! is_container_running; then
        print_warning "Test database is not running"
        return 0
    fi

    docker-compose -f ${COMPOSE_FILE} down

    print_success "Test database stopped successfully"
}

# Function to restart the test database
restart_db() {
    print_status "Restarting test PostgreSQL database..."
    stop_db
    start_db
}

# Function to show database status
status_db() {
    if is_container_running; then
        print_success "Test database is running"
        echo "Container: ${CONTAINER_NAME}"
        echo "Port: ${DB_PORT}"
        echo "Database: ${DB_NAME}"
        echo "User: ${DB_USER}"

        # Show container details
        echo ""
        print_status "Container details:"
        docker ps --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    else
        print_warning "Test database is not running"

        if is_container_exists; then
            print_status "Container exists but is stopped"
            docker ps -a --filter "name=${CONTAINER_NAME}" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        fi
    fi
}

# Function to clean up (remove container and volumes)
cleanup_db() {
    print_status "Cleaning up test database (removing container and volumes)..."

    docker-compose -f ${COMPOSE_FILE} down -v

    print_success "Test database cleaned up successfully"
}

# Function to show logs
logs_db() {
    if is_container_running; then
        print_status "Showing test database logs:"
        docker-compose -f ${COMPOSE_FILE} logs ${SERVICE_NAME}
    else
        print_error "Test database is not running"
        exit 1
    fi
}

# Function to connect to database
connect_db() {
    if ! is_container_running; then
        print_error "Test database is not running"
        exit 1
    fi

    print_status "Connecting to test database..."
    docker exec -it ${CONTAINER_NAME} psql -U ${DB_USER} -d ${DB_NAME}
}

# Function to show help
show_help() {
    echo "Test Database Management Script"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  start     Start the test PostgreSQL database"
    echo "  stop      Stop the test PostgreSQL database"
    echo "  restart   Restart the test PostgreSQL database"
    echo "  status    Show the status of the test database"
    echo "  logs      Show the database logs"
    echo "  connect   Connect to the database with psql"
    echo "  cleanup   Remove the container and volumes"
    echo "  help      Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 start      # Start the test database"
    echo "  $0 stop       # Stop the test database"
    echo "  $0 status     # Check if database is running"
}

# Main script logic
main() {
    check_docker

    case "${1:-help}" in
        start)
            start_db
            ;;
        stop)
            stop_db
            ;;
        restart)
            restart_db
            ;;
        status)
            status_db
            ;;
        logs)
            logs_db
            ;;
        connect)
            connect_db
            ;;
        cleanup)
            cleanup_db
            ;;
        help|--help|-h)
            show_help
            ;;
        *)
            print_error "Unknown command: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# Run main function with all arguments
main "$@"
