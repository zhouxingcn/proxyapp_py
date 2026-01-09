import socket
import threading

# Minimal SOCKS5 server supporting NO AUTH and CONNECT command only.
# Designed for local testing only (not production-grade).

class Socks5Server:
    def __init__(self, host='localhost', port=1080):
        self.host = host
        self.port = port
        self._running = False
        self._sock = None

    def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self.host, self.port))
        self._sock.listen(5)
        self._running = True
        while self._running:
            try:
                client, addr = self._sock.accept()
                t = threading.Thread(target=self.handle_client, args=(client,), daemon=True)
                t.start()
            except Exception:
                break

    def stop(self):
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass

    def handle_client(self, conn):
        try:
            # Greeting
            data = conn.recv(2)
            if not data or len(data) < 2:
                conn.close()
                return
            ver = data[0]
            nmethods = data[1]
            methods = conn.recv(nmethods)
            # reply: version 5, NO AUTH (0x00)
            conn.send(bytes([0x05, 0x00]))

            # request
            hdr = conn.recv(4)
            if not hdr or len(hdr) < 4:
                conn.close()
                return
            ver, cmd, rsv, atyp = hdr[0], hdr[1], hdr[2], hdr[3]
            if ver != 0x05:
                conn.close()
                return
            if cmd != 0x01:
                # only support CONNECT
                # reply: general failure
                conn.send(bytes([0x05, 0x07, 0x00, 0x01, 0,0,0,0, 0,0]))
                conn.close()
                return

            if atyp == 0x01:
                addr = conn.recv(4)
                dest_addr = socket.inet_ntoa(addr)
            elif atyp == 0x03:
                length = conn.recv(1)[0]
                dest_addr = conn.recv(length).decode('utf-8')
            elif atyp == 0x04:
                addr = conn.recv(16)
                # IPv6 not supported in this stub
                dest_addr = None
            else:
                conn.close()
                return
            port_bytes = conn.recv(2)
            dest_port = int.from_bytes(port_bytes, 'big')

            # try to connect to dest
            try:
                remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                remote.settimeout(5.0)
                remote.connect((dest_addr, dest_port))
            except Exception:
                # reply: general failure
                conn.send(bytes([0x05, 0x01, 0x00, 0x01, 0,0,0,0, 0,0]))
                conn.close()
                return

            # reply success
            # bind addr/port set to zeros
            conn.send(bytes([0x05, 0x00, 0x00, 0x01, 0,0,0,0, 0,0]))

            # relay
            def relay(src, dst):
                try:
                    while True:
                        data = src.recv(4096)
                        if not data:
                            break
                        dst.sendall(data)
                except Exception:
                    pass
                finally:
                    try:
                        dst.shutdown(socket.SHUT_RDWR)
                    except Exception:
                        pass

            t1 = threading.Thread(target=relay, args=(conn, remote), daemon=True)
            t2 = threading.Thread(target=relay, args=(remote, conn), daemon=True)
            t1.start()
            t2.start()
            t1.join()
            t2.join()
        except Exception:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

if __name__ == '__main__':
    s = Socks5Server('localhost', 1080)
    try:
        s.start()
    except KeyboardInterrupt:
        s.stop()
