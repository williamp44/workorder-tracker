import os

# mysql+aiomysql://user:pass@host:3306/dbname for MariaDB; SQLite for quick local runs.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
