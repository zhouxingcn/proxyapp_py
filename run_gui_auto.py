import tkinter as tk
import threading
import time

from main_gui import ProxyGUI


def run_gui():
    root = tk.Tk()
    app = ProxyGUI(root)

    # 预设配置并自动启动代理（不修改系统代理）
    app.proxy_enabled.set(True)
    app.auto_set_system_proxy.set(False)

    # 在主循环开始后短暂延迟执行启动，确保界面已完全初始化
    def do_start():
        app.start_proxy()
    root.after(500, do_start)

    root.mainloop()

if __name__ == '__main__':
    run_gui()
