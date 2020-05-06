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


import rich

# from ipaddress import ip_interface
# from netifaces import interfaces, ifaddresses


# def get_interface_ips():
#     return [
#         ip_interface(addr["addr"] + "/" + addr["netmask"])
#         for res in interfaces()
#         for addr in ifaddresses(res).get(AF_INET, [])
#     ]


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
            rich.print(self.clients.nodes)
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
        # self.daemon = True
        self.hostname = gethostname()
        self.port = port
        self.sender = socket(AF_INET, SOCK_DGRAM)
        self.sender.setsockopt(SOL_SOCKET, SO_BROADCAST, True)

    def run(self):
        data = {"hostname": self.hostname}
        while True:
            raw = pickle.dumps(data)
            self.sender.sendto(raw, ("255.255.255.255", self.port))
            time.sleep(2)


nodes = Nodes()
sa = ServiceAnnouncer()
nl = NodeListener(nodes=nodes)

sa.start()
nl.start()
