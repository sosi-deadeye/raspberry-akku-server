import os, stat, errno
import fuse
from fuse import Fuse

import database
import csv
import io


if not hasattr(fuse, '__version__'):
    raise RuntimeError("your fuse-py doesn't know of fuse.__version__, probably it's too old.")

fuse.fuse_python_api = (0, 2)


class MyStat(fuse.Stat):
    def __init__(self):
        self.st_mode = 0
        self.st_ino = 0
        self.st_dev = 0
        self.st_nlink = 0
        self.st_uid = 0
        self.st_gid = 0
        self.st_size = 0
        self.st_atime = 0
        self.st_mtime = 0
        self.st_ctime = 0


class HelloFS(Fuse):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _cts = [
            (str(cycle), ts) for (cycle, ts) in
            database.session.query(
                database.Cycle.cycle,
                database.Cycle.timestamp,
            ).all()
        ]
        self.cycles, self.timestamps = zip(*_cts)
        self.database  = {}

    def getattr(self, path):
        st = MyStat()
        if path == '/':
            st.st_mode = stat.S_IFDIR | 0o755
            st.st_nlink = 2
        elif path.rsplit('/', 1)[-1] in self.cycles:
            idx = self.cycles.index(path.rsplit('/', 1)[-1])
            st.st_mtime = int(self.timestamps[idx].timestamp())
            st.st_mode = stat.S_IFREG | 0o555
            st.st_nlink = 1
            st.st_size = 0
        else:
            return -errno.ENOENT
        return st

    def readdir(self, path, offset):
        curdir = os.curdir
        pardir = os.pardir
        for r in (curdir, pardir, *self.cycles):
            directory = fuse.Direntry(r)
            print(directory, r)
            yield directory

    def open(self, path, flags):
        accmode = os.O_RDONLY | os.O_WRONLY | os.O_RDWR
        if (flags & accmode) != os.O_RDONLY:
            return -errno.EACCES




def main():
    usage="""
Userspace hello example
""" + Fuse.fusage
    server = HelloFS(version="%prog " + fuse.__version__,
                     usage=usage,
                     dash_s_do='setsingle')

    server.parse(errex=1)
    server.main()

if __name__ == '__main__':
    main()