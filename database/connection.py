"""
STF Digital Twin - Database Connection Management
"""

import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base, seed_inventory_slots, seed_hardware_devices

_engine = None
_SessionFactory = None

def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        # Convert mysql:// to mysql+pymysql:// for SQLAlchemy
        if url.startswith("mysql://"):
            url = url.replace("mysql://", "mysql+pymysql://", 1)
        return url
    return "sqlite:///./stf_digital_twin.db"

def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            get_database_url(),
            echo=os.environ.get("SQL_ECHO", "false").lower() == "true",
            pool_pre_ping=True,
        )
    return _engine

def get_session_factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine())
    return _SessionFactory

@contextmanager
def get_session() -> Generator[Session, None, None]:
    SessionFactory = get_session_factory()
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def get_db_session() -> Session:
    SessionFactory = get_session_factory()
    return SessionFactory()

def init_database(seed_data: bool = True):
    engine = get_engine()
    Base.metadata.create_all(engine)
    if seed_data:
        with get_session() as session:
            seed_inventory_slots(session)
            seed_hardware_devices(session)
    print("Database initialized successfully")

def get_db():
    db = get_db_session()
    try:
        yield db
    finally:
        db.close()
