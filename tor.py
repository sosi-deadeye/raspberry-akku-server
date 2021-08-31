import time
import json
from socket import gethostname
from pathlib import Path
from threading import Thread

try:
    from emails import Message
except ImportError:
    raise SystemExit("Please install the emails package\n\npip3 install emails")


class Sender:
    def __init__(self, config="/media/data/email.json"):
        with open(config) as fd:
            email = json.load(fd)

        self.smtp = {
            "user": email["email_login"],
            "password": email["email_password"],
            "host": email["email_smtp_server"],
            "port": email["email_smtp_port"],
            "timeout": 10,
            "tls": email["email_smtp_ssl"],
        }
        self.mail_to = email["email_to"]
        self.mail_from = email["email_from"]

    def send(self, subject, text):
        Thread(target=self._send, args=(subject, text)).start()

    def _send(self, subject, text):
        return (
            Message(
                subject=subject,
                mail_from=self.mail_from,
                mail_to=self.mail_to,
                text=text,
            )
            .send(smtp=self.smtp)
            .error
        )


hostname = gethostname()
onion = Path("/var/lib/tor/ssh/hostname")

sender = Sender()
sender.send(hostname, "Ich bin online")

while True:
    if onion.exists():
        sender.send(hostname, onion.read_text())
        break
    time.sleep(10)
