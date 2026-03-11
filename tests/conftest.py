import os


def pytest_configure(config):
    """Set safe environment defaults before any test module is imported."""
    os.environ.setdefault("DATABASE_URL", "sqlite:///test.db")
    os.environ.setdefault("OPENAI_API_KEY", "test-key")
    os.environ.setdefault("ADMIN_PASSWORD", "test-password")
