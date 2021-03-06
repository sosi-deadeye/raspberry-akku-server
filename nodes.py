import time
import pickle
from socket import (
    AF_INET,
    SOCK_DGRAM,
    SOL_SOCKET,
    SO_BROADCAST,
    SO_REUSEPORT,
    gethostname,
    socket,
    timeout as SockTimeout,
)
from threading import Thread

import errors
import current_values


class Nodes:
    def __init__(self, timeout=5):
        self.timeout = timeout
        self._nodes = {}

    def _delete_nodes(self):
        for node_addr, node in self._nodes.copy().items():
            if (time.monotonic() - node["last_seen"]) > 5:
                del self._nodes[node_addr]

    def add(self, addr, payload):
        if not payload.get("last_seen"):
            payload["last_seen"] = time.monotonic()
        self._nodes[addr] = payload

    @property
    def nodes(self):
        self._delete_nodes()
        return self._nodes


class NodeListener(Thread):
    def __init__(self, *args, port=2020, nodes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.daemon = True
        self.hostname = gethostname()
        self.port = port
        self.clients = nodes or Nodes()
        self.receiver = None
        self.create_socket()

    def create_socket(self):
        self.receiver = socket(AF_INET, SOCK_DGRAM)
        self.receiver.setsockopt(SOL_SOCKET, SO_REUSEPORT, True)
        self.receiver.settimeout(2)
        self.receiver.bind(("255.255.255.255", self.port))

    def handle_data(self, client_data, client_addr):
        try:
            client_data = pickle.loads(client_data)
        except ValueError:
            print("Malformed data")
            return

        # todo: Replacement of /tmp/current_values.bin?
        if client_data.get("hostname") == self.hostname:
            client_data["self"] = True
        else:
            client_data["self"] = False

        client_data["last_seen"] = time.monotonic()
        self.clients.add(client_addr[0], client_data)

    def run(self):
        while True:
            try:
                client_data, client_addr = self.receiver.recvfrom(4096)
            except SockTimeout:
                pass
            except OSError:
                print("IP has been changed, resetting receiver socket")
                self.receiver.close()
                del self.receiver
                time.sleep(10)
                print("Creating new receiver socket")
                self.create_socket()
            else:
                self.handle_data(client_data, client_addr)
            time.sleep(0.05)


class ServiceAnnouncer(Thread):
    def __init__(self, *args, port=2020, **kwargs):
        super().__init__(*args, **kwargs)
        self.daemon = True
        self.hostname = gethostname()
        self.port = port
        self.sender = None
        self.create_socket()
        self.settings = {}

    def update_settings(self, settings: dict):
        self.settings.update(settings)

    def create_socket(self):
        self.sender = socket(AF_INET, SOCK_DGRAM)
        self.sender.setsockopt(SOL_SOCKET, SO_BROADCAST, True)

    def run(self):
        data = {"hostname": self.hostname}
        while True:
            data.update({"payload": current_values.get_values()})
            data.update({"settings": self.settings})
            data["payload"]["error_msg"] = errors.get_short(data["payload"]["error"])
            data["payload"]["error_msg_long"] = errors.get_msg(data["payload"]["error"])
            raw = pickle.dumps(data)
            try:
                self.sender.sendto(raw, ("255.255.255.255", self.port))
            except OSError:
                print("IP has been changed, resetting sender socket")
                self.sender.close()
                del self.sender
                time.sleep(10)
                print("Creating new sender socket")
                self.create_socket()
            time.sleep(2)


class NodeServer:
    def __init__(self, port=2020):
        self._nodes = Nodes()
        self.sa = ServiceAnnouncer()
        self.nl = NodeListener(nodes=self._nodes)

    def start(self) -> None:
        self.sa.start()
        self.nl.start()

    def update_settings(self, settings: dict):
        self.sa.settings.update(settings)

    @property
    def nodes(self) -> dict:
        return self._nodes.nodes.copy()

    @property
    def nodes_sorted(self) -> dict:
        return dict(sorted(self.nodes.items(), key=lambda x: x[1]["hostname"]))


if __name__ == "__main__":
    node_server = NodeServer()
    node_server.start()
    try:
        while True:
            time.sleep(2)
            print(node_server.nodes)
    except KeyboardInterrupt:
        pass
