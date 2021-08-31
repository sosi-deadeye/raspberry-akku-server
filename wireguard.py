import getpass
import json
import re
import shlex
import ssl
import subprocess
import sys
from collections import namedtuple
from email.message import EmailMessage
from smtplib import SMTP_SSL, SMTP
from pathlib import Path
from socket import gethostname

WG_CONFIG = Path("/media/data/wg0.conf")
PRIVATE_RE = re.compile(r"^PrivateKey = (.+)$", flags=re.MULTILINE)
Keys = namedtuple("Keys", "private public")

template = """
[Interface]
Address = 10.10.10.100/24
PrivateKey = {private}

[Peer]
PublicKey = n4ipJGlJ7YZ2X+jDmqQPXTwBRJmC+4mZ82Tbm8a5hg0=
AllowedIPs = 10.10.10.0/24
Endpoint = 5.9.16.40:51820
""".lstrip()

email_template = """
Hallo Andre,

ich bin jetzt online und du kannst meinen Public-Key als Peer hinzufügen.

Hier ist mein Public-Key: {public}
Das ist meine Adresse: {address}

Copy & Paste

[Peer]
PublicKey = {public}
AllowedIPs = 10.10.10.100/32



Schöne Grüße

--

Der {hostname}
""".lstrip()


def gen_keys(private=None):
    cmd_private = shlex.split("wg genkey")
    cmd_public = shlex.split("wg pubkey")
    if private is None:
        private = subprocess.check_output(cmd_private, encoding="utf8").strip()
    public = subprocess.check_output(cmd_public, input=private, encoding="utf8").strip()
    return Keys(private, public)


def enable():
    if WG_CONFIG.exists():
        config = WG_CONFIG.read_text()
        match = PRIVATE_RE.search(config)
        if match:
            keys = gen_keys(match.group(1))
    else:
        keys = gen_keys()
        config = template.format(private=keys.private, public=keys.public)
        WG_CONFIG.write_text(config)


def disable():
    if WG_CONFIG.exists():
        WG_CONFIG.unlink()


def test():
    with open("/media/data/email.json") as fd:
        settings = json.load(fd)

    if not WG_CONFIG.exists():
        sys.exit(1)

    hostname = gethostname()
    keys = gen_keys(PRIVATE_RE.search(WG_CONFIG.read_text()).group(1))
    nachricht = email_template.format(public=keys.public, address="10.10.10.100", hostname=hostname)

    smtp = SMTP(settings["email_smtp_server"], settings["email_smtp_port"])
    smtp.ehlo()
    smtp.starttls()
    smtp.login(settings["email_login"], settings["email_password"])
    # msg = email.message_from_string("Testnachricht")
    msg = EmailMessage()
    msg['subject'] = f"{hostname} ist online"
    msg['From'] = settings["email_from"]
    msg['To'] = settings["email_to"]
    msg.set_content(nachricht)
    smtp.send_message(msg, from_addr=settings["email_from"], to_addrs=[settings["email_to"]])
    smtp.close()


if __name__ == "__main__":
    enable()
    test()
