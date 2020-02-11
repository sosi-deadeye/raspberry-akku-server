import json
import xml.etree.ElementTree as ET
from argparse import ArgumentParser

import requests


def get_from_isp(domain, email):
    """
    Read: https://developer.mozilla.org/de/docs/Mozilla/Thunderbird/Autokonfiguration#Configuration_server_at_ISP
    """
    isp = f'http://autoconfig.{domain}/mail/config-v1.1.xml?emailaddress={email}'
    auto = f'https://{domain}/.well-known/autoconfig/mail/config-v1.1.xml'
    try:
        req = requests.get(isp, timeout=2)
    except:
        try:
            req = requests.get(auto, timeout=2)
        except:
            return None
    try:
        xml = ET.fromstring(req.content)
    except:
        return None
    return xml


def get_from_mozilla(domain):
    """
    Read: https://developer.mozilla.org/de/docs/Mozilla/Thunderbird/Autokonfiguration#ISPDB
    """
    try:
        req = requests.get(f'https://autoconfig.thunderbird.net/v1.1/{domain}', timeout=2)
    except:
        return None
    try:
        xml = ET.fromstring(req.content)
    except:
        return None
    return xml


def email_rep(text, user, address):
    """
    https://developer.mozilla.org/en-US/docs/Mozilla/Thunderbird/Autoconfiguration/FileFormat/HowTo#Username
    """
    text = text.replace('%EMAILADDRESS%', address)
    text = text.replace('%EMAILLOCALPART%', user)
    return text


def parse_xml(xml, user, address):
    """
    https://developer.mozilla.org/en-US/docs/Mozilla/Thunderbird/Autoconfiguration/FileFormat/HowTo#Definition
    """
    results = []
    for server in xml.findall('emailProvider/outgoingServer'):
        result = {
            'email_smtp_server': server.find('hostname').text,
            'email_smtp_port': int(server.find('port').text),
            'email_smtp_ssl': server.find('socketType').text in ('STARTTLS', 'SSL'),
            'email_login': email_rep(
                server.find('username').text,
                user,
                address),
            #'auth': server.find('authentication').text,
        }
        results.append(result)
    # [{'hostname': 'securesmtp.t-online.de', 'port': 587, 'sock_type': 'STARTTLS', 'username': 'am1982@t-online.de', 'auth': 'password-cleartext'}]
    return max(results, key=lambda r: r['email_smtp_port'])


def parse_email(email):
    username, domain = email.strip().rsplit('@', 1)
    return username, domain


def get_smtp(email):
    try:
        username, domain = parse_email(email)
    except ValueError:
        return []
    xml = get_from_isp(domain, email) or get_from_mozilla(domain)
    try:
        return parse_xml(xml, username, email)
    except:
        return []


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('email', help='E-Mail Adresse')
    args = parser.parse_args()
    result = get_smtp(args.email)
    print(result)
