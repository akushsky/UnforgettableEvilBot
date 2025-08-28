import os

# Load environment variables from .env file
try:
    from dotenv import load_dotenv

    # Prefer explicit TEST_ENV_FILE if set; otherwise load .env
    test_env_file = os.getenv("TEST_ENV_FILE")
    if test_env_file and os.path.exists(test_env_file):
        load_dotenv(test_env_file)
    else:
        load_dotenv()
except ImportError:
    pass


class Settings:
    """Settings class."""

    def __init__(self):
        """Initialize the class."""
        # Main settings
        self.DEBUG = os.getenv("DEBUG", "false").lower() == "true"
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

        # Database
        database_url = os.getenv(
            "DATABASE_URL", "postgresql://user:password@localhost:5432/whatsapp_digest"
        )
        # Fix old postgres:// format to postgresql://
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        self.DATABASE_URL = database_url

        # OpenAI
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        self.OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "1000"))
        self.OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))

        # Telegram
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
        # Disable SSL verification in DEBUG mode
        default_ssl_verify = "false" if self.DEBUG else "true"
        self.TELEGRAM_SSL_VERIFY = (
            os.getenv("TELEGRAM_SSL_VERIFY", default_ssl_verify).lower() == "true"
        )

        # JWT
        self.SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
        self.ALGORITHM = "HS256"
        self.ACCESS_TOKEN_EXPIRE_MINUTES = int(
            os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
        )

        # CORS
        self.CORS_ORIGINS = os.getenv(
            "CORS_ORIGINS",
            "http://localhost:3000,http://localhost:9090,http://localhost:9876",
        ).split(",")

        # Redis for caching
        self.REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.REDIS_ENABLED = os.getenv("REDIS_ENABLED", "true").lower() == "true"

        # Performance settings
        self.MAX_WORKERS = int(os.getenv("MAX_WORKERS", "10"))
        self.MAX_PROCESS_WORKERS = int(os.getenv("MAX_PROCESS_WORKERS", "4"))
        self.CACHE_TTL_DEFAULT = int(os.getenv("CACHE_TTL_DEFAULT", "3600"))
        self.DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "20"))
        self.DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "30"))

        # Data cleanup settings
        self.CLEANUP_OLD_MESSAGES_DAYS = int(
            os.getenv("CLEANUP_OLD_MESSAGES_DAYS", "30")
        )
        self.CLEANUP_OLD_SYSTEM_LOGS_DAYS = int(
            os.getenv("CLEANUP_OLD_SYSTEM_LOGS_DAYS", "7")
        )
        self.CLEANUP_COMPLETED_TASKS_HOURS = int(
            os.getenv("CLEANUP_COMPLETED_TASKS_HOURS", "24")
        )

        # WhatsApp settings
        self.WHATSAPP_SESSION_PATH = os.getenv(
            "WHATSAPP_SESSION_PATH", "./whatsapp_sessions"
        )
        self.WHATSAPP_BRIDGE_URL = os.getenv(
            "WHATSAPP_BRIDGE_URL", "http://localhost:3000"
        )

        # Async processor settings
        self.SKIP_ASYNC_PROCESSOR = (
            os.getenv("SKIP_ASYNC_PROCESSOR", "false").lower() == "true"
        )

        # Repository optimization settings
        self.USE_OPTIMIZED_REPOSITORIES = (
            os.getenv("USE_OPTIMIZED_REPOSITORIES", "false").lower() == "true"
        )

        # Testing settings
        self.TESTING = os.getenv("TEST_ENV_FILE") is not None

        # Admin settings
        self.ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")

        # Server settings
        self.PORT = int(os.getenv("PORT", "9876"))

        # Flag for deferred validation
        self._validated = False

    def validate_required_settings(self):
        """Validation of critical settings (called only when necessary)"""
        if self._validated:
            return

        required_vars = [
            ("OPENAI_API_KEY", self.OPENAI_API_KEY),
            ("TELEGRAM_BOT_TOKEN", self.TELEGRAM_BOT_TOKEN),
            ("SECRET_KEY", self.SECRET_KEY),
        ]

        missing_vars = []
        for var_name, var_value in required_vars:
            if not var_value or var_value == "your-secret-key-here":
                missing_vars.append(var_name)

        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )

        self._validated = True


# Global settings instance
settings = Settings()
