import tkinter as tk
import urllib.request
import time

from main_gui import ProxyGUI


def run_test_via_gui():
    root = tk.Tk()
    app = ProxyGUI(root)

    # 预设并自动启动代理（不修改系统代理）
    app.proxy_enabled.set(True)
    app.auto_set_system_proxy.set(False)

    def start_and_request():
        app.start_proxy()

        # 等待代理完全启动
        def do_client():
            try:
                proxy_handler = urllib.request.ProxyHandler({'http': 'http://localhost:8080', 'https': 'http://localhost:8080'})
                opener = urllib.request.build_opener(proxy_handler)
                urllib.request.install_opener(opener)
                url = 'http://httpbin.org/get'
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = resp.read(2048)
                    print('Client got status:', resp.status)
                    print(data[:256])
            except Exception as e:
                print('Client request error:', e)

            # 停止代理并退出 GUI
            try:
                app.stop_proxy()
            except Exception:
                pass
            root.after(500, root.destroy)

        root.after(1500, do_client)

    root.after(500, start_and_request)
    root.mainloop()

if __name__ == '__main__':
    run_test_via_gui()
