from subprocess import Popen, call, check_output, CalledProcessError
from threading import Timer


def pull():
    cmd = ["git", "pull", "--rebase"]
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


def fetch():
    call(["git", "fetch", "-p", "-P", "--all"])


def branches():
    cmd = ["git", "branch", "--remote", "-l"]
    stdout = check_output(cmd, encoding="utf8")
    return [line.strip().rpartition("/")[2] for line in stdout.splitlines()][1:]


def switch(branch):
    repository = "https://github.com/sosi-deadeye/raspberry-akku-server.git"
    call(["git", "pull", repository, branch, "--rebase"])
    call(["git", "checkout", branch])


def current_branch():
    for branch in map(str.strip, check_output(["git", "branch"], encoding="utf8").splitlines()):
        if branch.startswith("*"):
            return branch.replace("*", "").strip()
    else:
        return ""


def _restart():
    cmd = ["systemctl", "restart", "server", "api"]
    Popen(cmd)


def restart():
    Timer(2, _restart).start()
