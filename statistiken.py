import datetime
from io import BytesIO
import matplotlib.pyplot as plt
from typing import List


from database import (
    session,
    Statistik,
    Configuration,
    get_cycle,
    desc, asc,
)


def plot(cycle, history):
    """
    Statistiken aus [cycle] der letzen [history] plotten
    """
    last_ts = session.query(Statistik.timestamp).order_by(desc(Statistik.id)).filter(Statistik.cycle == cycle).first()
    if not last_ts:
        return b'<p>Statistik ist nicht vorhanden</p>'
    from_ts = last_ts[0] - datetime.timedelta(hours=history)
    statistiken = session.query(
        Statistik.voltage,
        Statistik.current,
        Statistik.charge,
        Statistik.timestamp).filter(
            Statistik.cycle == cycle,
            Statistik.timestamp > from_ts,
        ).all()
    if not statistiken:
        return b'<p>Fehler beim Rendern.</p>'
    voltages, currents, charges, timestamps = zip(*statistiken)
    x = [ -abs(last_ts[0] - ts).seconds / 3600 for ts in timestamps]
    capacity = session.query(Configuration.capacity).order_by(desc(Configuration.id)).filter(Configuration.cycle == cycle).first()
    if not capacity:
        capacity = 120.0
    else:
        capacity = capacity[0]
    capacity *= 1.1

    V = plt.subplot(311)
    V.plot(x, voltages, 'b-')
    V.set_title('Spannung in V')
    #V.set_xticks([])
    V.set_ylim([0, 15])

    I = plt.subplot(312)
    I.set_title('Strom in A')
    I.plot(x, currents, 'r-')
    #I.set_xticks([])
    I.set_ylim([-250, 250])

    C = plt.subplot(313)
    C.set_title('Ladung in Ah')
    C.plot(x, charges, 'g-')
    C.set_ylim([0, capacity])
    C.set_xlabel('Stunden')

    plt.tight_layout()

    image = BytesIO()
    plt.savefig(image, format='svg')
    plt.close()
    image.seek(0)
    return image.read()
