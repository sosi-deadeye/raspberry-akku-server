import mmap
import struct


def _get_values():
        """
        Format:
        5i: id, row, cycle, capacity, error
        9f: voltage, current, charge, temperature, timestamp, 4 x cell_voltages
        """
        st = struct.Struct('<5i9f')
        with open('/media/data/current_values.bin', 'rb') as fd:
            with mmap.mmap(fd.fileno(), st.size, prot=mmap.PROT_READ) as mm:
                return st.unpack_from(mm, 0)



def get_values():
    try:
        values = _get_values()
    except:
        return {}
    topics = ('id', 'row', 'cycle', 'capacity', 'error', 'voltage', 'current', 'charge', 'temperature', 'timestamp')
    data = dict(zip(topics, values))
    cell_voltages = values[-4:]
    data['cell_voltages'] = cell_voltages
    return data


