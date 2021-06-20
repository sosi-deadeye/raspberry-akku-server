import datetime
from pathlib import Path
from typing import Generator, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

from database import (
    Session,
    Statistik,
    Configuration,
    desc,
)

timezone_file = Path("/etc/timezone")
tz = ZoneInfo(timezone_file.read_text().strip())


def get_stats(
    session: Session, cycle: int, history: Optional[float] = None, rounding: Optional[int] = None
) -> Generator[str, None, None]:
    round_func = (
        (lambda x: x) if rounding is None else (lambda x: round(x, rounding))
    )
    whitespace = " "
    header = (
        "timestamp",
        "voltage",
        "current",
        "charge",
        "temperature",
        "cell_voltages",
    )
    yield ",".join(header) + "\n"
    if history is not None:
        start = datetime.datetime.utcnow() - datetime.timedelta(hours=history)
        query = (
            session.query(Statistik)
            .filter(Statistik.cycle == cycle, Statistik.timestamp > start)
            .all()
        )
    else:
        query = session.query(Statistik).filter(Statistik.cycle == cycle).all()
    for row in query:
        csv_row = (
            row.timestamp.astimezone(tz).isoformat()[:-6],
            round_func(row.voltage),
            round_func(row.current),
            round_func(row.charge),
            round_func(row.temperature),
            [round_func(v) for v in row.cell_voltages],
        )

        yield ",".join(
            f'"{col}"' if whitespace in col else f"{col}" for col in map(str, csv_row)
        ) + "\n"
