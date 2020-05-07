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
        self.receiver = socket(AF_INET, SOCK_DGRAM)
        self.receiver.setsockopt(SOL_SOCKET, SO_REUSEPORT, True)
        self.receiver.settimeout(2)
        self.receiver.bind(("255.255.255.255", self.port))
        self.clients = nodes or Nodes()

    def handle_data(self, client_data, client_addr):
        try:
            client_data = pickle.loads(client_data)
        except ValueError:
            print("Malformed data")
            return

        if client_data.get("hostname") == self.hostname:
            return

        client_data["last_seen"] = time.monotonic()
        self.clients.add(client_addr, client_data)

    def run(self):
        while True:
            try:
                client_data, client_addr = self.receiver.recvfrom(4096)
            except SockTimeout:
                pass
            else:
                self.handle_data(client_data, client_addr)
            time.sleep(0.05)


class ServiceAnnouncer(Thread):
    def __init__(self, *args, port=2020, **kwargs):
        super().__init__(*args, **kwargs)
        self.daemon = True
        self.hostname = gethostname()
        self.port = port
        self.sender = socket(AF_INET, SOCK_DGRAM)
        self.sender.setsockopt(SOL_SOCKET, SO_BROADCAST, True)

    def run(self):
        data = {"hostname": self.hostname}
        while True:
            data.update({"payload": current_values.get_values()})
            raw = pickle.dumps(data)
            self.sender.sendto(raw, ("255.255.255.255", self.port))
            time.sleep(2)


class NodeServer:
    def __init__(self, port=2020):
        self._nodes = Nodes()
        self.sa = ServiceAnnouncer()
        self.nl = NodeListener(nodes=self._nodes)

    def start(self):
        self.sa.start()
        self.nl.start()

    @property
    def nodes(self):
        current_nodes = self._nodes.nodes.copy()
        return {payload["hostname"]: addr[0] for addr, payload in current_nodes.items()}


if __name__ == "__main__":
    node_server = NodeServer()
    node_server.start()
    try:
        while True:
            time.sleep(2)
            print(node_server.nodes)
    except KeyboardInterrupt:
        pass
