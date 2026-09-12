import socket


def find_available_port(start_port: int) -> int:
    for port in range(start_port, start_port + 1000):
        if is_port_available(port):
            return port
    raise RuntimeError(f"No available port found starting at {start_port}")


def is_port_available(port: int) -> bool:
    for host in ("127.0.0.1", ""):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                return False
    return True
