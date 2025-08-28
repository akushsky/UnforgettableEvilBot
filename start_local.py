#!/usr/bin/env python3
"""
Local development startup script for WhatsApp Digest System
This script starts all services locally with PostgreSQL running in Docker

Usage:
    python start_local.py [--kill] [--restart]
    --kill      Kill existing processes and exit
    --restart   Kill existing processes and start fresh
"""

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

from config.settings import settings


class LocalDevelopmentServer:
    def __init__(self):
        self.processes = {}
        self.running = True

    def log(self, message):
        """Print timestamped log messages"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {message}")

    def find_existing_processes(self):
        """Find existing system processes"""
        existing_processes: dict[str, list] = {"bridge": [], "api": [], "postgres": []}

        try:
            for proc in psutil.process_iter(["pid", "name", "cmdline"]):
                try:
                    cmdline = " ".join(proc.info["cmdline"] or [])

                    # Check for WhatsApp bridge (persistent_bridge.js)
                    if "persistent_bridge.js" in cmdline or (
                        "node" in cmdline and "bridge" in cmdline
                    ):
                        existing_processes["bridge"].append(proc)

                    # Check for FastAPI/uvicorn on port 8000
                    elif "uvicorn" in cmdline and (
                        "main:app" in cmdline or "8000" in cmdline
                    ):
                        existing_processes["api"].append(proc)

                    # Check for postgres processes
                    elif proc.info["name"] and "postgres" in proc.info["name"].lower():
                        existing_processes["postgres"].append(proc)

                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                ):
                    continue

        except Exception as e:
            self.log(f"⚠️ Warning: Could not scan all processes: {e}")

        return existing_processes

    def kill_existing_processes(self, force=False):  # noqa: C901
        """Kill existing system processes"""
        self.log("🔍 Scanning for existing processes...")
        existing = self.find_existing_processes()

        killed_any = False

        # Kill bridge processes
        if existing["bridge"]:
            self.log(f"🔴 Found {len(existing['bridge'])} WhatsApp Bridge process(es)")
            for proc in existing["bridge"]:
                try:
                    self.log(
                        f"   Killing PID {proc.pid}: {' '.join(proc.cmdline()[:3])}"
                    )
                    proc.terminate()
                    killed_any = True

                    # Wait for graceful termination
                    try:
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        if force:
                            self.log(f"   Force killing PID {proc.pid}")
                            proc.kill()
                            proc.wait()

                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    self.log(f"   Could not kill PID {proc.pid}: {e}")

        # Kill API processes
        if existing["api"]:
            self.log(f"🔴 Found {len(existing['api'])} FastAPI process(es)")
            for proc in existing["api"]:
                try:
                    self.log(
                        f"   Killing PID {proc.pid}: {' '.join(proc.cmdline()[:3])}"
                    )
                    proc.terminate()
                    killed_any = True

                    try:
                        proc.wait(timeout=5)
                    except psutil.TimeoutExpired:
                        if force:
                            self.log(f"   Force killing PID {proc.pid}")
                            proc.kill()
                            proc.wait()

                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    self.log(f"   Could not kill PID {proc.pid}: {e}")

        if killed_any:
            self.log("⏳ Waiting for processes to shut down...")
            time.sleep(3)
            self.log("✅ Existing processes killed")
        else:
            self.log("✅ No existing processes found")

        return killed_any

    def check_ports_available(self):
        """Check if required ports are available"""
        import socket

        # Ports that should be free (application ports)
        ports_to_check = {3000: "WhatsApp Bridge", settings.PORT: "FastAPI"}

        unavailable_ports = []

        for port, service in ports_to_check.items():
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                result = sock.connect_ex(("localhost", port))
                if result == 0:
                    unavailable_ports.append((port, service))
            finally:
                sock.close()

        # Check PostgreSQL separately - if it's running, that's good
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            result = sock.connect_ex(("localhost", 5432))
            if result == 0:
                self.log("✅ PostgreSQL is already running on port 5432")
            else:
                self.log("⚠️ PostgreSQL is not running on port 5432")
                self.log(
                    "   Please start it with: docker-compose -f docker-compose.dev.yml up -d"
                )
        finally:
            sock.close()

        # Check Redis separately - if it's running, that's good
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            result = sock.connect_ex(("localhost", 6379))
            if result == 0:
                self.log("✅ Redis is already running on port 6379")
            else:
                self.log("⚠️ Redis is not running on port 6379")
                self.log(
                    "   Please start it with: docker-compose -f docker-compose.dev.yml up -d redis"
                )
        finally:
            sock.close()

        if unavailable_ports:
            self.log("⚠️ Some ports are already in use:")
            for port, service in unavailable_ports:
                self.log(f"   Port {port} ({service}) is occupied")
            return False
        else:
            self.log("✅ Required application ports are available")
            return True

    def run_command(self, command, name, log_file=None, cwd=None):
        """Run a command and track the process"""
        try:
            # Split command into list for security
            if isinstance(command, str):
                import shlex

                cmd_list = shlex.split(command)
            else:
                cmd_list = command

            if log_file:
                with open(log_file, "w") as f:
                    process = subprocess.Popen(
                        cmd_list,
                        stdout=f,
                        stderr=f,
                        cwd=cwd,
                        preexec_fn=os.setsid if os.name != "nt" else None,
                    )
            else:
                process = subprocess.Popen(
                    cmd_list,
                    cwd=cwd,
                    preexec_fn=os.setsid if os.name != "nt" else None,
                )
            self.processes[name] = process
            return process
        except Exception as e:
            self.log(f"❌ Failed to start {name}: {e}")
            return None

    def check_health(self, url, max_attempts=30):
        """Check if a service is healthy"""
        for i in range(max_attempts):
            try:
                import httpx

                # Use httpx instead of urllib for better security
                with httpx.Client(timeout=5.0) as client:
                    response = client.get(url)
                    if response.status_code == 200:
                        return True
            except BaseException:
                if i < max_attempts - 1:
                    time.sleep(2)
        return False

    def check_database(self):
        """Check database connection"""
        self.log("🔍 Checking database connection...")
        try:
            from sqlalchemy import text

            from app.database.connection import engine

            for i in range(10):
                try:
                    with engine.connect() as conn:
                        conn.execute(text("SELECT 1"))
                    self.log("✅ Database is ready!")
                    return True
                except Exception:
                    self.log(f"⏳ Waiting for database... ({i + 1}/10)")
                    if i == 9:
                        self.log("❌ Database connection failed!")
                        self.log(
                            "Make sure PostgreSQL is running with: docker-compose -f docker-compose.dev.yml up -d"
                        )
                        return False
                    time.sleep(2)
        except ImportError:
            self.log(
                "❌ Cannot import database modules. Make sure dependencies are installed."
            )
            return False

    def check_redis(self):
        """Check Redis connection"""
        self.log("🔍 Checking Redis connection...")
        try:
            import socket

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(("localhost", 6379))
            sock.close()

            if result == 0:
                self.log("✅ Redis is running!")
                return True
            else:
                self.log("❌ Redis is not running on port 6379")
                return False
        except Exception as e:
            self.log(f"❌ Error checking Redis: {e}")
            return False

    def start_redis(self):
        """Start Redis container"""
        self.log("🚀 Starting Redis container...")
        try:
            result = subprocess.run(
                ["docker-compose", "-f", "docker-compose.dev.yml", "up", "-d", "redis"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                self.log("✅ Redis container started successfully")
                # Wait for Redis to be ready
                time.sleep(3)
                return True
            else:
                self.log(f"❌ Failed to start Redis: {result.stderr}")
                return False
        except Exception as e:
            self.log(f"❌ Error starting Redis: {e}")
            return False

    def run_migrations(self):
        """Run database migrations"""
        self.log("🔄 Running database migrations...")
        try:
            result = subprocess.run(
                ["alembic", "upgrade", "head"], capture_output=True, text=True
            )
            if result.returncode == 0:
                self.log("✅ Database migrations completed")
                return True
            else:
                self.log(f"❌ Migration failed: {result.stderr}")
                return False
        except FileNotFoundError:
            self.log("❌ Alembic not found. Make sure it's installed.")
            return False

    def setup_directories(self):
        """Create necessary directories"""
        Path("whatsapp_sessions").mkdir(exist_ok=True)
        Path("logs").mkdir(exist_ok=True)
        self.log("📁 Created necessary directories")

    def install_node_dependencies(self):
        """Install Node.js dependencies for WhatsApp bridge"""
        bridge_dir = Path("whatsapp_bridge")
        if not bridge_dir.exists():
            self.log("❌ WhatsApp bridge directory not found")
            return False

        if not (bridge_dir / "node_modules").exists():
            self.log("📦 Installing WhatsApp Bridge dependencies...")
            try:
                subprocess.run(["npm", "install"], cwd=bridge_dir, check=True)
                self.log("✅ Node.js dependencies installed")
            except (subprocess.CalledProcessError, FileNotFoundError):
                self.log(
                    "❌ Failed to install Node.js dependencies. Make sure Node.js and npm are installed."
                )
                return False
        return True

    def start_bridge(self):
        """Start WhatsApp bridge"""
        self.log("🌉 Starting WhatsApp Bridge...")
        process = self.run_command(
            ["node", "persistent_bridge.js"],
            "bridge",
            "logs/bridge.log",
            cwd=str(Path("whatsapp_bridge")),
        )

        if process:
            self.log("⏳ Waiting for WhatsApp Bridge to be ready...")
            if self.check_health(f"{settings.WHATSAPP_BRIDGE_URL}/health"):
                self.log("✅ WhatsApp Bridge is ready!")
                return True
            else:
                self.log("❌ WhatsApp Bridge failed to start. Check logs/bridge.log")
                return False
        return False

    def start_api(self):
        """Start FastAPI application"""
        self.log("🐍 Starting FastAPI application...")
        process = self.run_command(
            f"uvicorn main:app --host 127.0.0.1 --port {settings.PORT} --reload",
            "api",
            "logs/api.log",
        )

        if process:
            self.log("⏳ Waiting for FastAPI to be ready...")
            # Use /health as readiness probe
            if self.check_health(f"http://localhost:{settings.PORT}/health"):
                self.log("✅ FastAPI is ready!")
                return True
            else:
                self.log(
                    "❌ FastAPI failed to become ready (health). Check logs/api.log"
                )
                return False
        return False

    def restore_connections(self):
        """Restore WhatsApp connections"""
        try:
            import httpx

            # Use httpx instead of urllib for better security
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{settings.WHATSAPP_BRIDGE_URL}/restore-all", data=b""
                )
                if response.status_code == 200:
                    self.log("🔄 Auto-reconnection initiated")
                else:
                    self.log("⚠️ Auto-reconnection failed")
        except BaseException:
            self.log("⚠️ Could not initiate auto-reconnection")

    def monitor_processes(self):
        """Monitor and restart failed processes"""
        while self.running:
            time.sleep(10)

            for name, process in self.processes.items():
                if process.poll() is not None:  # Process has died
                    self.log(f"❌ {name.title()} died, restarting...")
                    if name == "bridge":
                        self.start_bridge()
                    elif name == "api":
                        self.start_api()

    def cleanup(self, signum=None, frame=None):
        """Clean up processes"""
        self.log("📛 Shutting down services...")
        self.running = False

        for name, process in self.processes.items():
            try:
                if os.name != "nt":
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                else:
                    process.terminate()
                process.wait(timeout=10)
            except BaseException:
                try:
                    if os.name != "nt":
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    else:
                        process.kill()
                except BaseException:
                    pass

        self.log("✅ Services stopped")
        sys.exit(0)

    def start(self):
        """Start the development server"""
        # Set up signal handlers
        signal.signal(signal.SIGINT, self.cleanup)
        signal.signal(signal.SIGTERM, self.cleanup)

        self.log("🚀 Starting WhatsApp Digest System (Local Development)...")

        # Check prerequisites
        if not self.check_database():
            sys.exit(1)

        # Ensure Redis is running
        if not self.check_redis():
            self.log("⚠️ Redis is not running. Starting Redis...")
            self.start_redis()

        if not self.run_migrations():
            sys.exit(1)

        self.setup_directories()

        if not self.install_node_dependencies():
            sys.exit(1)

        # Start services
        if not self.start_bridge():
            sys.exit(1)

        self.restore_connections()

        if not self.start_api():
            sys.exit(1)

        # Show status
        self.log("🎉 All services are running!")
        self.log(f"📊 FastAPI: http://localhost:{settings.PORT}")
        self.log(f"🌉 Bridge: {settings.WHATSAPP_BRIDGE_URL}")
        self.log(f"📋 Admin Panel: http://localhost:{settings.PORT}/admin")
        self.log("")
        self.log("📝 Logs:")
        self.log("   API: logs/api.log")
        self.log("   Bridge: logs/bridge.log")
        self.log("")
        self.log("🛑 Press Ctrl+C to stop all services")

        # Start monitoring in a separate thread
        monitor_thread = threading.Thread(target=self.monitor_processes, daemon=True)
        monitor_thread.start()

        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.cleanup()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Local Development Server for WhatsApp Digest System"
    )
    parser.add_argument(
        "--kill", action="store_true", help="Kill existing processes and exit"
    )
    parser.add_argument(
        "--restart", action="store_true", help="Kill existing processes and start fresh"
    )

    args = parser.parse_args()

    if args.kill:
        server = LocalDevelopmentServer()
        server.kill_existing_processes(force=True)
        sys.exit(0)

    if args.restart:
        server = LocalDevelopmentServer()
        server.kill_existing_processes(force=True)
        time.sleep(2)  # Wait a moment before restarting
        server.start()
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help"]:
        print(
            """
🚀 Local Development Server for WhatsApp Digest System

Usage: python start_local.py

Prerequisites:
1. Start PostgreSQL: docker-compose -f docker-compose.dev.yml up -d
2. Install Python dependencies: pip install -r requirements.txt
3. Install Node.js and npm

This script will:
- Check database connection
- Run migrations
- Install Node.js dependencies
- Start WhatsApp Bridge on port 3000
        - Start FastAPI on port {settings.PORT}
- Monitor and restart failed services
        """
        )
        sys.exit(0)

    server = LocalDevelopmentServer()

    # Check ports before starting
    if not server.check_ports_available():
        sys.exit(1)

    server.start()


if __name__ == "__main__":
    main()
