#!/usr/bin/env python3

import json
import emails
import jinja2


html_tpl = """
<html>
  <head>
  </head>
  <body>
    <ul>
    {% for error in msg.splitlines() %}
        <li>{{error}}</li>
    {% endfor %}
    </ul>
  </body>
</html>
""".lstrip()

tpl = jinja2.Template(html_tpl)


def send_report(topic):
    try:
        return _send_report(topic)
    except:
        return {"success": False, "status": 0}


def _send_report(topic):
    with open('/media/data/email.json') as fd:
        settings = json.load(fd)
    with open('/etc/hostname') as fd:
        hostname = fd.read().strip()
    html = tpl.render(msg=topic)
    smtp = {
        'host': settings['email_smtp_server'],
        'port': settings['email_smtp_port'], 'timeout': 5,
        'tls': settings['email_smtp_ssl'],
        'user': settings['email_login'],
        'password': settings['email_password'],
    }
    message = emails.Message(
        html=html,
        subject='Fehlermeldung',
        mail_from=(hostname, settings['email_from'])
    )
    r = message.send(to=[settings['email_to']], smtp=smtp)
    if r.status_code == 250:
        # print('Success')
        return {"success": True, "status": 250}
    else:
        # print('Error:', r.status_code)
        return {"success": False, "status": r.status_code}


if __name__ == '__main__':
    send_report('Testbenachrichtigung')
