import socket
import threading
import time
import logging
import ipaddress
from urllib.parse import urlparse

# optional dependency: PySocks (pip install pysocks)
try:
    import socks
    HAS_PYSOCKS = True
except Exception:
    socks = None
    HAS_PYSOCKS = False


class ProxyServer:
    def __init__(self, local_host='localhost', local_port=8080, socks_host='localhost', socks_port=1080,
                 logger=None, success_ttl: int = 300, fail_ttl: int = 30,
                 bypass_list=None, proxy_list=None, log_level=None):
        self.local_host = local_host
        self.local_port = local_port
        self.socks_host = socks_host
        self.socks_port = int(socks_port)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.running = False
        # logger may be a callable for GUI integration; also use stdlib logging
        self.logger = logger
        self._logger = logging.getLogger('ProxyServer')
        if log_level is not None:
            self._logger.setLevel(log_level)

        # reachability cache: (host,port) -> (success:bool, expires_at:float)
        self._reach_cache = {}
        self._success_ttl = int(success_ttl)
        self._fail_ttl = int(fail_ttl)

        # lists for bypassing or forcing proxy. Accept list of domains, ips, or CIDR.
        self.bypass_list = bypass_list or []
        self.proxy_list = proxy_list or []
        # keep track of client threads so we can attempt to join them on stop
        self._client_threads = []

    def _log(self, message: str):
        try:
            # stdlib logger
            try:
                self._logger.info(message)
            except Exception:
                pass

            # GUI-style logger callable (if provided)
            if self.logger:
                try:
                    self.logger(message)
                except Exception:
                    pass
        except Exception:
            pass
        
    def start(self):
        """启动代理服务器"""
        try:
            self.socket.bind((self.local_host, self.local_port))
            self.socket.listen(5)
            self.running = True
            self._log(f"Proxy server started on {self.local_host}:{self.local_port}")

            while self.running:
                try:
                    client_socket, addr = self.socket.accept()
                except OSError:
                    # socket was likely closed via stop(); exit loop
                    break
                except Exception as e:
                    self._log(f"Accept error: {e}")
                    continue

                t = threading.Thread(target=self.handle_client, args=(client_socket,), daemon=True)
                t.start()
                self._client_threads.append(t)

        except Exception as e:
            self._log(f"Error starting proxy server: {e}")
    
    def stop(self):
        """停止代理服务器"""
        self.running = False
        try:
            self.socket.close()
        except Exception:
            pass

        # attempt to join client threads briefly
        for t in list(self._client_threads):
            try:
                if t.is_alive():
                    t.join(timeout=0.2)
            except Exception:
                pass

        self._client_threads.clear()
        self._log("Proxy server stopped")
        
    def handle_client(self, client_socket):
        """处理客户端请求（以 bytes 安全方式读取并根据方法分发）"""
        try:
            client_socket.settimeout(5.0)

            # 读取请求头（直到 CRLFCRLF）
            header_data = b''
            while b'\r\n\r\n' not in header_data:
                chunk = client_socket.recv(4096)
                if not chunk:
                    break
                header_data += chunk

            if not header_data:
                return

            # 解析首行
            try:
                header_text = header_data.decode('iso-8859-1')
            except Exception:
                header_text = header_data.decode('utf-8', errors='ignore')

            lines = header_text.split('\r\n')
            first_line = lines[0].strip()
            # log the received request to the provided logger (thread-safe)
            self._log(f"Received request: {first_line}")

            if first_line.upper().startswith('CONNECT'):
                self.handle_connect_request(client_socket, first_line)
            else:
                # 处理普通HTTP请求（包含可能的请求体）
                # 支持 Content-Length 或 Transfer-Encoding: chunked
                content_length = 0
                chunked = False
                for l in lines[1:]:
                    if not l:
                        break
                    parts = l.split(':', 1)
                    if len(parts) == 2:
                        key = parts[0].lower()
                        val = parts[1].strip()
                        if key == 'content-length':
                            try:
                                content_length = int(val)
                            except Exception:
                                content_length = 0
                        elif key == 'transfer-encoding' and 'chunked' in val.lower():
                            chunked = True

                body = b''
                sep = b'\r\n\r\n'
                idx = header_data.find(sep)
                already = 0
                if idx != -1:
                    already = len(header_data) - (idx + len(sep))
                    if already > 0:
                        body = header_data[-already:]

                if content_length > 0:
                    while len(body) < content_length:
                        more = client_socket.recv(4096)
                        if not more:
                            break
                        body += more
                elif chunked:
                    # read remaining chunked body from client (preserve chunk encoding)
                    body += self._read_chunked_body(client_socket)

                self.handle_http_request(client_socket, header_data, body)

        except Exception as e:
            self._log(f"Error handling client: {e}")
        finally:
            try:
                client_socket.close()
            except Exception:
                pass

    def handle_connect_request(self, client_socket, first_line):
        """处理HTTPS CONNECT请求：通过上游 SOCKS 建立到目标的隧道，然后双向转发（二进制）"""
        try:
            target_url = first_line.split()[1]
            host, port = self.parse_host_port(target_url)
            # decide whether to bypass proxy according to lists
            if self._host_in_list(host, self.proxy_list):
                # forced to proxy; skip direct attempt
                direct_sock = None
            else:
                # 首先尝试直连目标
                direct_sock = self._try_direct_connect(host, port, timeout=3.0)
            if direct_sock:
                try:
                    client_socket.send(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                except Exception:
                    try:
                        direct_sock.close()
                    except Exception:
                        pass
                    return

                # 直连成功，双向转发
                self.forward_data(client_socket, direct_sock)
                try:
                    direct_sock.close()
                except Exception:
                    pass
                return

            # 直连失败，尝试通过上游 SOCKS 回退
            if not HAS_PYSOCKS:
                try:
                    client_socket.send(b"HTTP/1.1 502 Bad Gateway\r\n\r\nPySocks not installed and direct connect failed")
                except Exception:
                    pass
                return

            try:
                socks_sock = socks.socksocket()
                socks_sock.set_proxy(socks.SOCKS5, self.socks_host, self.socks_port)
                socks_sock.settimeout(10.0)
                socks_sock.connect((host, port))

                # 回复客户端连接已建立
                client_socket.send(b"HTTP/1.1 200 Connection Established\r\n\r\n")

                # 双向转发（二进制）
                self.forward_data(client_socket, socks_sock)
                try:
                    socks_sock.close()
                except Exception:
                    pass
            except Exception as e:
                self._log(f"Error in CONNECT request handling (socks fallback): {e}")
                try:
                    client_socket.send(b"HTTP/1.1 502 Bad Gateway\r\n\r\nCONNECT failed")
                except Exception:
                    pass

        except Exception as e:
            self._log(f"Error in CONNECT request handling: {e}")
    
    def handle_http_request(self, client_socket, header_bytes, body_bytes):
        """处理 HTTP 请求：通过上游 SOCKS 连接目标并发送原始请求（调整请求行为相对路径），然后将响应原样返回给客户端"""
        try:
            # 解析 header_text
            try:
                header_text = header_bytes.decode('iso-8859-1')
            except Exception:
                header_text = header_bytes.decode('utf-8', errors='ignore')

            lines = header_text.split('\r\n')
            first_line = lines[0]
            parts = first_line.split()
            if len(parts) < 3:
                return
            method, url_or_path, version = parts[0], parts[1], parts[2]

            parsed = urlparse(url_or_path)
            if parsed.scheme and parsed.hostname:
                host = parsed.hostname
                port = parsed.port or (80 if parsed.scheme == 'http' else 443)
                path = parsed.path or '/'
                if parsed.query:
                    path += '?' + parsed.query
            else:
                # 从 Host 头获取主机
                host = None
                port = None
                for l in lines[1:]:
                    if not l:
                        break
                    k_v = l.split(':', 1)
                    if len(k_v) == 2 and k_v[0].lower() == 'host':
                        host_port = k_v[1].strip()
                        if ':' in host_port:
                            hp = host_port.split(':')
                            host = hp[0]
                            try:
                                port = int(hp[1])
                            except Exception:
                                port = 80
                        else:
                            host = host_port
                            port = 80
                        break
                path = url_or_path if url_or_path.startswith('/') else '/'

            if host is None:
                try:
                    client_socket.send(b"HTTP/1.1 400 Bad Request\r\n\r\nMissing Host")
                except Exception:
                    pass
                return

            # 重写请求首行为相对路径（origin server 需要）
            new_first = f"{method} {path} {version}\r\n"

            # 过滤 Proxy-Connection 头并确保 Connection: close（简单处理）
            new_headers = []
            for l in lines[1:]:
                if not l:
                    break
                if l.lower().startswith('proxy-connection:'):
                    continue
                if l.lower().startswith('connection:'):
                    # replace with close
                    continue
                new_headers.append(l)
            new_headers.append('Connection: close')
            header_out = new_first + '\r\n'.join(new_headers) + '\r\n\r\n'

            # body_bytes already read by caller
            request_out = header_out.encode('iso-8859-1') + (body_bytes or b'')

            # 如果 host 在强制代理列表中，则跳过直连
            if self._host_in_list(host, self.proxy_list):
                direct_sock = None
            else:
                # 优先尝试直连：建立到目标的普通 TCP 连接并发送请求
                # 但先检查失败缓存以避免频繁尝试已知不可达目标
                cached = self._reach_cache.get((host, port))
                if cached is not None:
                    ok, expires = cached
                    if time.time() < expires and not ok:
                        # recent failure cached -> skip direct
                        direct_sock = None
                    else:
                        direct_sock = self._try_direct_connect(host, port, timeout=4.0)
                else:
                    direct_sock = self._try_direct_connect(host, port, timeout=4.0)
            if direct_sock:
                try:
                    direct_sock.sendall(request_out)
                except Exception as e:
                    self._log(f"Direct send failed, will try socks fallback: {e}")
                    try:
                        direct_sock.close()
                    except Exception:
                        pass
                    direct_sock = None

            if direct_sock:
                # 从直连读取并转发响应
                try:
                    while True:
                        data = direct_sock.recv(4096)
                        if not data:
                            break
                        try:
                            client_socket.sendall(data)
                        except Exception:
                            break
                except Exception as e:
                    self._log(f"Error relaying direct response: {e}")
                finally:
                    try:
                        direct_sock.close()
                    except Exception:
                        pass
                return

            # 直连不可用或发送失败 -> 回退到 SOCKS
            if not HAS_PYSOCKS:
                try:
                    client_socket.send(b"HTTP/1.1 502 Bad Gateway\r\n\r\nPySocks not installed and direct connect failed")
                except Exception:
                    pass
                return

            try:
                proxy_sock = socks.socksocket()
                proxy_sock.set_proxy(socks.SOCKS5, self.socks_host, self.socks_port)
                proxy_sock.settimeout(10.0)
                proxy_sock.connect((host, port))

                # send request and stream response back to client
                try:
                    proxy_sock.sendall(request_out)
                except Exception as e:
                    self._log(f"Error sending request to upstream: {e}")
                    try:
                        client_socket.send(b"HTTP/1.1 502 Bad Gateway\r\n\r\nUpstream send error")
                    except Exception:
                        pass
                    try:
                        proxy_sock.close()
                    except Exception:
                        pass
                    return

                # 接收并转发响应（二进制）
                try:
                    while True:
                        data = proxy_sock.recv(4096)
                        if not data:
                            break
                        try:
                            client_socket.sendall(data)
                        except Exception:
                            break
                except Exception as e:
                    self._log(f"Error relaying response: {e}")

                try:
                    proxy_sock.close()
                except Exception:
                    pass
            except Exception as e:
                self._log(f"Error connecting via socks: {e}")
                try:
                    client_socket.send(b"HTTP/1.1 502 Bad Gateway\r\n\r\nUpstream connect failed")
                except Exception:
                    pass

        except Exception as e:
            print(f"Error in HTTP request handling: {e}")

    def parse_host_port(self, url):
        """解析URL主机和端口"""
        parsed_url = urlparse(url)
        host = parsed_url.hostname
        port = parsed_url.port or (80 if parsed_url.scheme == 'http' else 443)
        
        # 对于CONNECT请求，url已经是host:port形式
        if ':' in url and not url.startswith('http'):
            parts = url.split(':')
            host = parts[0]
            port = int(parts[1])
            
        return host, port
    def _try_direct_connect(self, host, port, timeout=3.0):
        """尝试直接 TCP 连接到目标主机:port，使用 reachability cache，成功返回 socket（已连接），失败返回 None"""
        # Check bypass list: if host is in bypass_list (i.e., should not use proxy), we still allow direct
        # Check proxy_list is handled by caller
        key = (host, int(port))
        now = time.time()
        cached = self._reach_cache.get(key)
        if cached is not None:
            ok, expires = cached
            if now < expires:
                if not ok:
                    # recent failure -> skip trying
                    self._log(f"Skipping direct connect to {host}:{port} due to recent failure cache")
                    return None

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((host, port))
            s.settimeout(10.0)
            # record success
            self._reach_cache[key] = (True, now + self._success_ttl)
            self._log(f"Direct connect success to {host}:{port}")
            return s
        except Exception as e:
            # record failure
            self._reach_cache[key] = (False, now + self._fail_ttl)
            self._log(f"Direct connect failed to {host}:{port}: {e}")
            try:
                s.close()
            except Exception:
                pass
            return None

    def _host_in_list(self, host: str, lst) -> bool:
        """判断 host 是否与列表中的任一项匹配。列表项可以是域名（或后缀）、IP 或 CIDR。"""
        if not lst:
            return False
        for entry in lst:
            entry = str(entry).strip()
            if not entry:
                continue
            # CIDR
            if '/' in entry:
                try:
                    net = ipaddress.ip_network(entry, strict=False)
                    try:
                        addr = ipaddress.ip_address(host)
                        if addr in net:
                            return True
                    except Exception:
                        # host is not an IP literal; resolve? skip
                        pass
                except Exception:
                    pass
            else:
                # try IP literal match
                try:
                    if ipaddress.ip_address(host) == ipaddress.ip_address(entry):
                        return True
                except Exception:
                    # treat as domain suffix match
                    h = host.lower()
                    e = entry.lower()
                    if h == e or h.endswith('.' + e):
                        return True
        return False
    def _try_direct_connect(self, host, port, timeout=3.0):
        """尝试直接 TCP 连接到目标主机:port，成功返回 socket（已连接），失败返回 None"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect((host, port))
            # set a slightly larger timeout for subsequent operations
            s.settimeout(10.0)
            return s
        except Exception:
            try:
                s.close()
            except Exception:
                pass
            return None
    def _read_chunked_body(self, sock):
        """从套接字读取 chunked 编码的请求体，返回包含原始 chunked bytes 的字节串"""
        data = b''
        try:
            while True:
                # 读取chunk-size行
                size_line = b''
                while b'\r\n' not in size_line:
                    part = sock.recv(1)
                    if not part:
                        return data
                    size_line += part

                data += size_line
                try:
                    size = int(size_line.strip().split(b';')[0], 16)
                except Exception:
                    size = 0

                # 读取块数据和后面的 CRLF
                remaining = size + 2  # data + CRLF
                while remaining > 0:
                    chunk = sock.recv(min(4096, remaining))
                    if not chunk:
                        return data
                    data += chunk
                    remaining -= len(chunk)

                if size == 0:
                    # read and append trailing header terminator if any
                    # read until we see a blank line (\r\n)
                    trailer = b''
                    while True:
                        line = b''
                        while b'\r\n' not in line:
                            p = sock.recv(1)
                            if not p:
                                break
                            line += p
                        trailer += line
                        if line in (b'\r\n', b''):
                            break
                    data += trailer
                    break
        except Exception:
            pass
        return data
            
    def forward_data(self, client_socket, socks_socket):
        """双向转发数据"""
        def forward(src, dst):
            try:
                while True:
                    data = src.recv(4096)
                    if not data:
                        break
                    dst.send(data)
            except Exception:
                pass
        
        # 启动两个线程进行双向转发
        thread1 = threading.Thread(target=forward, args=(client_socket, socks_socket), daemon=True)
        thread2 = threading.Thread(target=forward, args=(socks_socket, client_socket), daemon=True)

        thread1.start()
        thread2.start()

        # wait briefly for threads to finish; they are daemon threads so will exit on program end
        try:
            while thread1.is_alive() or thread2.is_alive():
                thread1.join(timeout=0.1)
                thread2.join(timeout=0.1)
                if not self.running:
                    break
        except Exception:
            pass

if __name__ == '__main__':
    server = ProxyServer(8080)
    try:
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down proxy server...")
        server.stop()
