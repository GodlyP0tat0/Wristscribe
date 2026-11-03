"""Find the address other devices on the Wi-Fi can reach this laptop at."""

from __future__ import annotations

import socket


def lan_ip() -> str:
    # Connecting a UDP socket sends no packets; it only makes the OS pick the
    # outgoing interface, whose address is what the watch/iPhone should use.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()
