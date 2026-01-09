import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
from proxy_server import ProxyServer
from system_proxy import ProxyConfig
import queue
import logging
import json
from pathlib import Path

class ProxyGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("SOCKS代理转发器")
        self.root.geometry("1024x1024")
        
        # 本地代理（对应用程序可见）
        self.proxy_host = tk.StringVar()
        self.proxy_port = tk.StringVar()
        self.proxy_enabled = tk.BooleanVar()
        # 是否将系统代理设置为本地代理（启动时写入注册表）
        self.auto_set_system_proxy = tk.BooleanVar()

        # 上游 SOCKS 代理（将请求转发到该 SOCKS）
        self.upstream_host = tk.StringVar()
        self.upstream_port = tk.StringVar()

        # 运行时对象
        self.server = None
        self.server_thread = None
        self.sys_proxy = ProxyConfig()
        # 用于从后台线程安全地传递日志到 tkinter 主线程
        self.log_queue = queue.Queue()

        # config path (store next to this module)
        self.config_path = Path(__file__).resolve().parent / 'config.json'

        # 启动轮询队列的循环（在 init_widgets 之后会被调用）
        self.init_widgets()
        self.load_config()
        
    def init_widgets(self):
        # 主面板
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置面板
        config_frame = ttk.LabelFrame(main_frame, text="代理设置", padding="10")
        config_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # 本地代理地址输入
        tk.Label(config_frame, text="本地代理地址:").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(config_frame, textvariable=self.proxy_host).grid(row=0, column=1, sticky=(tk.E, tk.W), padx=5)
        
        tk.Label(config_frame, text="端口:").grid(row=0, column=2, sticky=tk.W, padx=(10, 0))
        ttk.Entry(config_frame, textvariable=self.proxy_port, width=8).grid(row=0, column=3, sticky=(tk.W), padx=5)
        
        # 启用代理复选框
        ttk.Checkbutton(config_frame, text="启用本地代理", variable=self.proxy_enabled).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=5)
        ttk.Checkbutton(config_frame, text="启动时设置系统代理", variable=self.auto_set_system_proxy).grid(row=1, column=2, columnspan=2, sticky=tk.W, pady=5)
        
        # 控制按钮
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=1, column=0, columnspan=2, pady=10)
        
        self.start_button = ttk.Button(button_frame, text="启动", command=self.start_proxy)
        self.start_button.grid(row=0, column=0, padx=5)
        
        self.stop_button = ttk.Button(button_frame, text="停止", command=self.stop_proxy)
        self.stop_button.grid(row=0, column=1, padx=5)
        
        # 日志显示区
        log_frame = ttk.LabelFrame(main_frame, text="日志", padding="10")
        log_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=5)
        
        self.log_text = tk.Text(log_frame, height=10, width=60)
        scroll_y = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll_y.set)
        
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scroll_y.grid(row=0, column=1, sticky=(tk.N, tk.S))
        # 让日志区域随父窗口拉伸
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(2, weight=1)
        # 确保第二列也不会被挤压（控制按钮所在列）
        main_frame.columnconfigure(1, weight=0)
        config_frame.columnconfigure(1, weight=1)
        config_frame.columnconfigure(3, weight=0)

        # 上游 SOCKS 配置行
        tk.Label(config_frame, text="上游 SOCKS 地址:").grid(row=2, column=0, sticky=tk.W, pady=(8,0))
        ttk.Entry(config_frame, textvariable=self.upstream_host).grid(row=2, column=1, sticky=(tk.E, tk.W), padx=5, pady=(8,0))
        tk.Label(config_frame, text="端口:").grid(row=2, column=2, sticky=tk.W, padx=(10, 0), pady=(8,0))
        ttk.Entry(config_frame, textvariable=self.upstream_port, width=8).grid(row=2, column=3, sticky=(tk.W), padx=5, pady=(8,0))

        # 启动日志队列的轮询（将会在主线程把后台消息刷入 Text）
        self._poll_log_queue()
        # 额外配置面板（高级）
        adv_frame = ttk.LabelFrame(main_frame, text="高级配置", padding="10")
        adv_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=5)

        tk.Label(adv_frame, text="直连绕过列表 (逗号分隔):").grid(row=0, column=0, sticky=tk.W)
        self.bypass_entry = ttk.Entry(adv_frame)
        self.bypass_entry.grid(row=0, column=1, sticky=(tk.E, tk.W), padx=5)

        tk.Label(adv_frame, text="强制代理列表 (逗号分隔):").grid(row=1, column=0, sticky=tk.W)
        self.proxylist_entry = ttk.Entry(adv_frame)
        self.proxylist_entry.grid(row=1, column=1, sticky=(tk.E, tk.W), padx=5)

        tk.Label(adv_frame, text="成功缓存 TTL (秒):").grid(row=2, column=0, sticky=tk.W)
        self.success_ttl = tk.StringVar(value='300')
        ttk.Entry(adv_frame, textvariable=self.success_ttl, width=8).grid(row=2, column=1, sticky=tk.W, padx=5)

        tk.Label(adv_frame, text="失败缓存 TTL (秒):").grid(row=3, column=0, sticky=tk.W)
        self.fail_ttl = tk.StringVar(value='30')
        ttk.Entry(adv_frame, textvariable=self.fail_ttl, width=8).grid(row=3, column=1, sticky=tk.W, padx=5)

        btn_frame2 = ttk.Frame(adv_frame)
        btn_frame2.grid(row=4, column=0, columnspan=2, pady=6)
        ttk.Button(btn_frame2, text="保存配置", command=self.save_config).grid(row=0, column=0, padx=5)
        ttk.Button(btn_frame2, text="载入配置", command=self.load_config_file).grid(row=0, column=1, padx=5)
        ttk.Button(btn_frame2, text="清除可达缓存", command=self.clear_reach_cache).grid(row=0, column=2, padx=5)

        adv_frame.columnconfigure(1, weight=1)
    def load_config(self):
        """加载配置"""
        # 默认本地监听
        self.proxy_host.set("localhost")
        self.proxy_port.set("8080")
        # 默认上游 SOCKS
        self.upstream_host.set("localhost")
        self.upstream_port.set("1080")
        # 默认不自动修改系统代理
        self.auto_set_system_proxy.set(True)
        # setup logging handler to forward to GUI queue
        self._setup_logging_handler()
        # 如果存在工作目录下的 config.json，则自动载入
        try:
            p = Path('config.json')
            if p.exists():
                self.load_config_file()
        except Exception:
            pass

    def _setup_logging_handler(self):
        import logging

        class QueueHandler(logging.Handler):
            def __init__(self, enqueue_callable):
                super().__init__()
                self.enqueue = enqueue_callable

            def emit(self, record):
                try:
                    msg = self.format(record)
                    self.enqueue(msg)
                except Exception:
                    pass

        handler = QueueHandler(self.enqueue_log)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger = logging.getLogger('ProxyServer')
        # avoid adding multiple handlers
        if not any(isinstance(h, QueueHandler) for h in logger.handlers):
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    def enqueue_log(self, message: str):
        """从后台线程安全地入队日志消息"""
        try:
            self.log_queue.put_nowait(message)
        except Exception:
            pass

    def _poll_log_queue(self):
        """轮询后台日志队列并把消息写入 Text（在主线程运行）"""
        try:
            while True:
                msg = self.log_queue.get_nowait()
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                self.log_text.insert(tk.END, f"[{timestamp}] {msg}\n")
                self.log_text.see(tk.END)
        except Exception:
            # queue.Empty 或其他异常都忽略
            pass
        finally:
            # 200ms 后再次轮询
            try:
                self.root.after(200, self._poll_log_queue)
            except Exception:
                pass
        
    def log_message(self, message):
        """写入日志"""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
    
    def start_proxy(self):
        """启动代理"""
        if not self.proxy_enabled.get():
            self.log_message("请先启用本地代理！")
            return

        try:
            local_port = int(self.proxy_port.get())
        except Exception:
            self.log_message("本地代理端口不是有效的整数")
            return

        try:
            upstream_port = int(self.upstream_port.get())
        except Exception:
            self.log_message("上游 SOCKS 端口不是有效的整数")
            return

        # 创建并启动代理服务器
        if self.server is None:
            # 将 enqueue_log 作为 logger 回调传给后台服务器，服务器线程会将日志入队
            bypass = [s.strip() for s in self.bypass_entry.get().split(',') if s.strip()] if hasattr(self, 'bypass_entry') else []
            proxylist = [s.strip() for s in self.proxylist_entry.get().split(',') if s.strip()] if hasattr(self, 'proxylist_entry') else []
            try:
                sttl = int(self.success_ttl.get())
            except Exception:
                sttl = 300
            try:
                fttl = int(self.fail_ttl.get())
            except Exception:
                fttl = 30

            self.server = ProxyServer(local_host=self.proxy_host.get(), local_port=local_port,
                                      socks_host=self.upstream_host.get(), socks_port=upstream_port,
                                      logger=self.enqueue_log, success_ttl=sttl, fail_ttl=fttl,
                                      bypass_list=bypass, proxy_list=proxylist)

        self.server_thread = threading.Thread(target=self.server.start, daemon=True)
        self.server_thread.start()

        # 可选：设置系统代理以指向本地
        if self.auto_set_system_proxy.get():
            ok = self.sys_proxy.set_system_proxy(self.proxy_host.get(), local_port, use_system_proxy=True)
            if ok:
                self.log_message("已设置系统代理")
            else:
                self.log_message("设置系统代理失败")

        self.log_message(f"正在启动本地代理 {self.proxy_host.get()}:{self.proxy_port.get()}")
        # 更新按钮状态
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        
    def stop_proxy(self):
        """停止代理"""
        # 停止服务器
        if self.server:
            try:
                self.server.stop()
                self.server = None
            except Exception as e:
                self.log_message(f"停止代理时出错: {e}")

        # 恢复系统代理
        if self.auto_set_system_proxy.get():
            ok = self.sys_proxy.restore_system_proxy()
            if ok:
                self.log_message("已还原系统代理设置")
            else:
                self.log_message("还原系统代理失败")

        # 如果有后台线程，尝试 join 一小段时间以便清理
        try:
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=1.0)
        except Exception:
            pass

        self.log_message("代理服务已停止")
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)

    def save_config(self):
        cfg = {
            'proxy_host': self.proxy_host.get(),
            'proxy_port': self.proxy_port.get(),
            'upstream_host': self.upstream_host.get(),
            'upstream_port': self.upstream_port.get(),
            'auto_set_system_proxy': bool(self.auto_set_system_proxy.get()),
            'bypass_list': [s.strip() for s in self.bypass_entry.get().split(',') if s.strip()] if hasattr(self, 'bypass_entry') else [],
            'proxy_list': [s.strip() for s in self.proxylist_entry.get().split(',') if s.strip()] if hasattr(self, 'proxylist_entry') else [],
            'success_ttl': int(self.success_ttl.get()) if self.success_ttl.get().isdigit() else 300,
            'fail_ttl': int(self.fail_ttl.get()) if self.fail_ttl.get().isdigit() else 30
        }
        try:
            p = self.config_path
            p.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
            msg = f"已保存配置到 {p.resolve()}"
            self.log_message(msg)
            try:
                messagebox.showinfo('保存配置', msg)
            except Exception:
                pass
        except Exception as e:
            err = f"保存配置失败: {e}"
            self.log_message(err)
            try:
                messagebox.showerror('保存配置失败', err)
            except Exception:
                pass

    def load_config_file(self):
        try:
            p = self.config_path
            if not p.exists():
                self.log_message(f'未找到 {p.resolve()}')
                try:
                    messagebox.showwarning('载入配置', f'未找到 {p.resolve()}')
                except Exception:
                    pass
                return
            data = json.loads(p.read_text(encoding='utf-8'))
            self.proxy_host.set(data.get('proxy_host', 'localhost'))
            self.proxy_port.set(str(data.get('proxy_port', '8080')))
            self.upstream_host.set(data.get('upstream_host', 'localhost'))
            self.upstream_port.set(str(data.get('upstream_port', '1080')))
            self.auto_set_system_proxy.set(bool(data.get('auto_set_system_proxy', True)))
            if hasattr(self, 'bypass_entry'):
                self.bypass_entry.delete(0, tk.END)
                self.bypass_entry.insert(0, ','.join(data.get('bypass_list', [])))
            if hasattr(self, 'proxylist_entry'):
                self.proxylist_entry.delete(0, tk.END)
                self.proxylist_entry.insert(0, ','.join(data.get('proxy_list', [])))
            self.success_ttl.set(str(data.get('success_ttl', 300)))
            self.fail_ttl.set(str(data.get('fail_ttl', 30)))
            msg = f'已载入 {p.resolve()}'
            self.log_message(msg)
            try:
                messagebox.showinfo('载入配置', msg)
            except Exception:
                pass
        except Exception as e:
            err = f'载入配置失败: {e}'
            self.log_message(err)
            try:
                messagebox.showerror('载入配置失败', err)
            except Exception:
                pass

    def clear_reach_cache(self):
        try:
            if self.server:
                # server keeps its own cache
                if hasattr(self.server, '_reach_cache'):
                    self.server._reach_cache.clear()
                    self.log_message('已清除服务器可达性缓存')
                    return
            # otherwise, nothing to clear
            self.log_message('没有运行中的服务器可清除缓存')
        except Exception as e:
            self.log_message(f'清除缓存失败: {e}')
        
    def run_proxy(self):
        """运行代理服务器"""
        try:
            # 这里可以添加实际的代理逻辑
            self.log_message("代理服务器启动成功！")
            while self.proxy_enabled.get():
                time.sleep(1)
        except Exception as e:
            self.log_message(f"发生错误: {str(e)}")

def main():
    root = tk.Tk()
    
    # 尝试设置外观主题（如果可用）
    try:
        style = ttk.Style()
        if style.theme_names():
            style.theme_use('clam')
    except:
        pass
    
    app = ProxyGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
