from wifi import Cell
from wifi.exceptions import InterfaceError


def get_cells():
    cells = []
    try:
        cells = list(Cell.all('wlan0'))
    except InterfaceError:
        try:
            cells = list(Cell.all('ap0'))
        except InterfaceError:
            return []
    return [c.ssid for c in cells]


def get_cells_format():
    return '\n'.join(get_cells())


if __name__ == '__main__':
    print(get_cells_format())
