from subprocess import Popen, call, check_output, CalledProcessError
from threading import Timer


def pull():
    cmd = ["git", "pull"]
    cwd = "/home/server/akku"
    return call(cmd, cwd=cwd) == 0


def get_last_commit():
    cmd = ["git", "show", "--summary"]
    cwd = "/home/server/akku"
    try:
        stdout = check_output(cmd, cwd=cwd, encoding="utf8")
    except CalledProcessError:
        stdout = ""
    return stdout


def _restart():
    cmd = ["systemctl", "restart", "server", "api"]
    Popen(cmd)


def restart():
    Timer(2, _restart).start()
