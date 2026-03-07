import os
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, UniqueConstraint, text
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./saci.db")

def utcnow():
    return datetime.utcnow().replace(tzinfo=None)

sqlite_connect_args = {"check_same_thread": False, "timeout": 60}
engine = create_engine(
    DATABASE_URL,
    connect_args=sqlite_connect_args if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class Gateway(Base):
    __tablename__ = "gateways"
    id = Column(Integer, primary_key=True)
    label = Column(String, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("host", "port", name="uix_gateways_host_port"),)

class Meter(Base):
    __tablename__ = "meters"
    id = Column(Integer, primary_key=True)
    gateway_id = Column(Integer, ForeignKey("gateways.id"), nullable=True)
    unit_id = Column(Integer, nullable=True)

    # New stable identity
    device_uid = Column(String, nullable=True, unique=True)

    # Mapping / config fields
    slot_code = Column(String, nullable=True)
    description = Column(String, nullable=True)
    phase = Column(String, nullable=True)
    status = Column(String, nullable=True, default="Activo")
    multiplier = Column(Float, nullable=True, default=1.0)
    owner_name = Column(String, nullable=True)
    parking_slot = Column(String, nullable=True)
    is_active = Column(Integer, nullable=False, default=1)

class Reading(Base):
    __tablename__ = "readings"
    id = Column(Integer, primary_key=True)
    ts_utc = Column(DateTime, index=True, default=utcnow)

    # Keep gateway/unit for troubleshooting & for legacy ingestion
    gateway_id = Column(Integer, ForeignKey("gateways.id"), nullable=True)
    unit_id = Column(Integer, nullable=True)

    # Preferred link
    meter_id = Column(Integer, ForeignKey("meters.id"), nullable=True)

    volt_v = Column(Float)
    current_a = Column(Float)
    power_kw = Column(Float)
    freq_hz = Column(Float)
    pf = Column(Float)
    kwh_import = Column(Float)

    ok = Column(Integer, nullable=True, default=1)
    error = Column(String, nullable=True)

def configure_sqlite():
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL"))
        conn.execute(text("PRAGMA synchronous=NORMAL"))
        conn.execute(text("PRAGMA busy_timeout=10000"))

def init_db():
    configure_sqlite()
    Base.metadata.create_all(engine)
