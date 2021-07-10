# raspberry-akku-server
- Controller-Version: 7.3
- Software-Version: 4.3.3

## Dienste
- api (Bereitstellung der Daten via http)
- server (Akquirieren der Daten)

Die Dienste sind via systemd konfiguriert und laufen aktuell noch mit root-Rechten.
Der Quellcode befindet sich in /home/server/akku
Die statischen Inhalte des Webservers befinden sich in /var/www/html

Die Dienste sind alle mit Python programmiert.
Es wird ein venv für den Interpreter verwendet (/home/server/venv)
Zum aktivieren des venv:

source /home/server/venv/bin/activate

