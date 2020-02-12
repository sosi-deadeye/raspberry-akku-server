from datetime import datetime

from sqlalchemy import (
    create_engine, Column,
    Integer, Float, DateTime, Boolean, desc, JSON,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import (
    sessionmaker,
    scoped_session,
)

Base = declarative_base()
engine = create_engine('sqlite:///stats.sqlite', connect_args={"check_same_thread": False})
Session = scoped_session(sessionmaker(bind=engine))


class Cycle(Base):
    __tablename__ = 'cycle'
    id = Column(Integer, primary_key=True)
    timestamp = Column('timestamp', DateTime, default=datetime.utcnow)
    cycle = Column('cycle', Integer, nullable=False)


class Configuration(Base):
    __tablename__ = 'configuration'
    id = Column(Integer, primary_key=True)
    cycle = Column(Integer, nullable=False)
    capacity = Column('capacity', Float)
    dimension = Column(Integer)
    settings = Column(Integer)


class State(Base):
    __tablename__ = 'state'
    id = Column(Integer, primary_key=True)
    cycle = Column(Integer, nullable=False)
    row = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    onoff = Column(Boolean, nullable=False)


class Error(Base):
    __tablename__ = 'error'
    id = Column(Integer, primary_key=True)
    row = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    cycle = Column(Integer, nullable=False)
    error = Column(Integer)


class Statistik(Base):
    __tablename__ = 'statistik'
    id = Column(Integer, primary_key=True)
    cycle = Column(Integer, nullable=False)
    row = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    voltage = Column(Float)
    current = Column(Float)
    charge = Column(Float)
    cell_voltages = Column(JSON)
    temperature = Column(Float)


Base.metadata.create_all(engine)


def to_dict(obj):
    if not obj:
        return {}
    return {
        key: value for key, value in
        vars(obj).items()
        if not key.startswith('_')
    }


# def get_stats(cycle):
#     yield ','.join(('timestamp', 'voltage', 'current', 'charge', 'temperature', 'cell_voltages'))
#     for row in query_stats(cycle):
#         csv_row = ','.join((row.timestamp.isoformat(), str(row.voltage), str(row.current), str(row.charge),
#                             str(row.temperature), f'"{row.cell_voltages}"')) + '\n'
#         yield csv_row

def get_cycle(session):
    cycle = session.query(Cycle.cycle).order_by(desc('id')).first()
    if cycle:
        return cycle[0]
    return 0


def set_cycle(session):
    cycle_id = get_cycle(session) + 1
    session.add(Cycle(cycle=cycle_id))
    session.commit()
    return cycle_id
