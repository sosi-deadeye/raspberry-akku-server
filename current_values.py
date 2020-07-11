import mmap
import struct
from pathlib import Path
from typing import Any, Iterable, Union, Tuple


class MemoryMappedStruct:
    def __init__(
        self,
        file: Union[Path, str],
        struct: struct.Struct,
        *,
        reader: bool = False,
        writer: bool = False,
        create: bool = False,
    ):
        self.file = Path(file)
        self.mm_st = struct
        self.create_file = create
        self.flush_mm = writer
        if reader and not writer:
            self.mm = self._get_mmap_reader()
        elif not reader and writer:
            self.mm = self._get_mmap_writer()
        elif not reader:
            raise ValueError("Must be a reader or a writer.")
        else:
            raise ValueError("Can't be a reader and writer.")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def _get_mmap_reader(self) -> mmap.mmap:
        with self.file.open("rb") as fd:
            return mmap.mmap(fd.fileno(), self.mm_st.size, access=mmap.ACCESS_READ)

    def _get_mmap_writer(self) -> mmap.mmap:
        if self.create_file:
            with self.file.open("wb") as fd:
                fd.write(b"\x00" * self.mm_st.size)
        with self.file.open("r+b") as fd:
            return mmap.mmap(
                fileno=fd.fileno(), length=self.mm_st.size, access=mmap.ACCESS_WRITE,
            )

    def close(self) -> None:
        if not self.mm.closed and self.flush_mm:
            self.mm.flush()
        self.mm.close()

    def get_values(self) -> Tuple[Any]:
        return self.mm_st.unpack_from(self.mm, 0)

    def set_values(self, values: Iterable[Any]):
        self.mm_st.pack_into(self.mm, 0, *values)


def _get_values(mmap_reader: MemoryMappedStruct, topics: Tuple[str, ...]):
    try:
        values = mmap_reader.get_values()
    except ValueError:
        return {}
    data = dict(zip(topics, values))
    cell_voltages = values[-4:]
    data["cell_voltages"] = cell_voltages
    return data


def get_values():
    return _get_values(MM_READER, TOPICS)


def set_values(values):
    return MM_WRITER.set_values(values)


FILE = "/tmp/current_values.bin"
STRUCT = struct.Struct("<5i9f")
TOPICS = (
    "id",
    "row",
    "cycle",
    "capacity",
    "error",
    "voltage",
    "current",
    "charge",
    "temperature",
    "timestamp",
)
MM_WRITER = MemoryMappedStruct(FILE, STRUCT, writer=True, create=True)
MM_READER = MemoryMappedStruct(FILE, STRUCT, reader=True)
