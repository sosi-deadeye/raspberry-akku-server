import sys
from argparse import ArgumentParser
from binascii import hexlify
from pathlib import Path
from hashlib import pbkdf2_hmac


CONFIG = """
country=de
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1

network={{
       ssid="{ssid}"
       psk={psk}
       # psk="{password}"
       # proto=RSN
       # key_mgmt=WPA-PSK
       # pairwise=CCMP
       # group=CCMP
}}
""".lstrip()


def gen_psk(ssid, password):
    password, ssid = map(str.encode, (password.replace(' ', ''), ssid))
    hash = pbkdf2_hmac('sha1', password, ssid, 4096, 32)
    return hexlify(hash).decode()

def set_network(ssid, password):
    if len(password) < 8:
        raise ValueError('Passwort ist zu kurz. Mindestens 8 Zeichen.')
    psk = gen_psk(ssid, password)
    wpa_supplicant = Path('/etc/wpa_supplicant/wpa_supplicant.conf')
    wpa_supplicant.write_text(
        CONFIG.format(ssid=ssid, psk=psk, password=password)
    )

