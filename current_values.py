import mmap
import struct

FD = None
MM = None


def _get_values():
    """
        Format:
        5i: id, row, cycle, capacity, error
        9f: voltage, current, charge, temperature, timestamp, 4 x cell_voltages
        """
    global FD, MM
    st = struct.Struct('<5i9f')
    if FD is None:
        FD = open('/media/data/current_values.bin', 'rb')
    if MM is None:
        MM = mmap.mmap(FD.fileno(), st.size, access=mmap.ACCESS_READ)
    return st.unpack_from(MM, 0)


def get_values():
    try:
        values = _get_values()
    except ValueError:
        return {}
    topics = ('id', 'row', 'cycle', 'capacity', 'error', 'voltage', 'current', 'charge', 'temperature', 'timestamp')
    data = dict(zip(topics, values))
    cell_voltages = values[-4:]
    data['cell_voltages'] = cell_voltages
    return data
