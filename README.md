# raspberry-akku-server

## Dienste
- api (Bereitstellung der Daten via http)
- server (Akquirieren der Daten)

Die Dienste sind via systemd konfiguriert und laufen aktuell noch mit root-Rechten.
Der Quellcode befindet sich in /root/akku
Die statischen Inhalte des Webservers befinden sich in /var/www/html

Die Dienste sind alle mit Python programmiert.
Es wird ein venv für den Interpreter verwendet (/root/venv)
Zum aktivieren des venv:

source /root/venv/bin/activate

Backup-Images können hier heruntergeladen werden: https://archive.server101.icu/.k-akku/
