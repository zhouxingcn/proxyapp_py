import threading
import time
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

from proxy_server import ProxyServer
from socks5_stub import Socks5Server

class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'{"ok": true, "via": "origin", "path": "%s"}' % self.path.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


def run_local_http_server(port=8001):
    httpd = HTTPServer(('localhost', port), SimpleHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd

if __name__ == '__main__':
    # start origin server
    httpd = run_local_http_server(8001)

    # start a simple socks5 stub on 1081
    socks = Socks5Server('localhost', 1081)
    ts = threading.Thread(target=socks.start, daemon=True)
    ts.start()

    time.sleep(0.5)

    # start proxy server with proxy_list forcing proxy usage and socks pointing at our stub
    server = ProxyServer(local_host='localhost', local_port=8080, socks_host='localhost', socks_port=1081,
                         logger=print, bypass_list=[], proxy_list=['localhost'], success_ttl=5, fail_ttl=2)
    t = threading.Thread(target=server.start, daemon=True)
    t.start()

    time.sleep(0.5)

    proxy_handler = urllib.request.ProxyHandler({'http': 'http://localhost:8080', 'https': 'http://localhost:8080'})
    opener = urllib.request.build_opener(proxy_handler)
    urllib.request.install_opener(opener)

    url = 'http://localhost:8001/test'
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = resp.read(2048)
            print('Response status:', resp.status)
            print('Response:', data)
    except Exception as e:
        print('Request error:', e)

    # cleanup
    try:
        server.stop()
    except Exception:
        pass
    try:
        socks.stop()
    except Exception:
        pass
    try:
        httpd.shutdown()
    except Exception:
        pass
    time.sleep(0.2)
