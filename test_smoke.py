import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

from proxy_server import ProxyServer


class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"ok": true, "path": "%s"}' % self.path.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        # suppress default logging
        return


def run_local_http_server(port=8000):
    httpd = HTTPServer(('localhost', port), SimpleHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


if __name__ == '__main__':
    # 启动本地 HTTP 服务，避免依赖外网
    httpd = run_local_http_server(8000)

    # 启动代理服务器线程（默认使用 direct-first, so it should reach localhost:8000 directly)
    server = ProxyServer(local_host='localhost', local_port=8080, socks_host='localhost', socks_port=1080, logger=print)
    t = threading.Thread(target=server.start, daemon=True)
    t.start()

    time.sleep(0.5)

    proxy_handler = urllib.request.ProxyHandler({'http': 'http://localhost:8080', 'https': 'http://localhost:8080'})
    opener = urllib.request.build_opener(proxy_handler)
    urllib.request.install_opener(opener)

    url = 'http://localhost:8000/test'
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read(2048)
            print('Response status:', resp.status)
            print('Response (first 512 bytes):')
            print(data[:512])
    except Exception as e:
        print('Request error:', e)

    # 停止服务器
    try:
        server.stop()
    except Exception as e:
        print('Error stopping server:', e)
    try:
        httpd.shutdown()
    except Exception:
        pass
    time.sleep(0.2)
