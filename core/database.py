# -*- coding: utf-8 -*-
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Database URI pour SQLite (evolutive vers PostgreSQL via change of URI)
BASE_DIR = Path(__file__).parent.parent  # racine du projet
DB_FILE = BASE_DIR / "database.db"  # SQLite file in working directory
DB_URI = f"sqlite:///{DB_FILE}"

# Create SQLAlchemy engine with future mode
engine = create_engine(DB_URI, echo=False, future=True)

# SessionLocal factory to generate new DB sessions
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


# Function to initialize database tables
def init_db():
    """Create all tables defined in models.py if not existing."""
    from core.models import Base  # import Base declarative

    Base.metadata.create_all(bind=engine)
