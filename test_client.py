import urllib.request

# 仅作为客户端：通过本地 HTTP 代理发送请求，不会启动服务器
proxy_handler = urllib.request.ProxyHandler({'http': 'http://localhost:8080', 'https': 'http://localhost:8080'})
opener = urllib.request.build_opener(proxy_handler)
urllib.request.install_opener(opener)

url = 'http://httpbin.org/get'
try:
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = resp.read(2048)
        print('Response status:', resp.status)
        print(data[:512])
except Exception as e:
    print('Request error:', e)
