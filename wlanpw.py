import re
import sys
from argparse import ArgumentParser
from pathlib import Path
from subprocess import check_output


def set_ap_pw(pw):
     if len(pw) < 8:
         raise ValueError('Password is too short')
     config = Path('/etc/hostapd/hostapd.conf')
     new_settings = re.sub(r'wpa_passphrase=.+', f'wpa_passphrase={pw}', config.read_text())
     config.write_text(new_settings)


def reset():
    set_ap_pw('12345678')


def set(pw):
    set_ap_pw(pw)

if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--reset', action='store_true', help='Passwort zurücksetzen')
    parser.add_argument('--set', help='Passwort setzen')
    args = parser.parse_args()
    if args.reset:
        reset()
    elif args.set:
        try:
            set(args.set)
        except ValueError:
            print('Passwort ist zu kurz. Mindestens 8 Zeichen sind erforderlich.', file=sys.stderr)
            sys.exit(1)

