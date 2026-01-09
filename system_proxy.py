import platform
import winreg
import ctypes
from pathlib import Path


class ProxyConfig:
    def __init__(self):
        self.proxy_key = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        # backup storage for existing settings so we can restore
        self._backup = {}
        self._is_windows = platform.system().lower() == 'windows'

    def _read_value(self, name):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.proxy_key) as key:
                val = winreg.QueryValueEx(key, name)
                return val[0]
        except Exception:
            return None

    def _refresh_windows_proxy(self):
        """通知系统代理设置已更改"""
        try:
            INTERNET_OPTION_SETTINGS_CHANGED = 39
            INTERNET_OPTION_REFRESH = 37
            internet_set_option = ctypes.windll.Wininet.InternetSetOptionW
            internet_set_option(0, INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
            internet_set_option(0, INTERNET_OPTION_REFRESH, 0, 0)
        except Exception:
            pass

    def set_system_proxy(self, proxy_host, proxy_port, use_system_proxy=True):
        """设置系统代理（并备份原有设置）"""
        if not self._is_windows:
            # Not on Windows: no-op
            return False

        try:
            # 备份现有值（首次调用备份）
            if not self._backup:
                self._backup['ProxyEnable'] = self._read_value('ProxyEnable')
                self._backup['ProxyServer'] = self._read_value('ProxyServer')

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.proxy_key, 0, winreg.KEY_WRITE) as key:
                if use_system_proxy:
                    # 启用代理
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                    proxy_address = f"{proxy_host}:{proxy_port}"
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_address)
                else:
                    # 禁用代理
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)

            # 通知系统刷新设置
            self._refresh_windows_proxy()
            return True
        except Exception as e:
            print(f"Failed to set system proxy: {e}")
            return False

    def restore_system_proxy(self):
        """还原系统代理配置（使用备份值）"""
        if not self._is_windows:
            return False

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.proxy_key, 0, winreg.KEY_WRITE) as key:
                if 'ProxyEnable' in self._backup and self._backup['ProxyEnable'] is not None:
                    winreg.SetValueEx(key, 'ProxyEnable', 0, winreg.REG_DWORD, int(bool(self._backup['ProxyEnable'])))
                else:
                    # 默认禁用
                    winreg.SetValueEx(key, 'ProxyEnable', 0, winreg.REG_DWORD, 0)

                # 恢复或删除 ProxyServer
                if 'ProxyServer' in self._backup and self._backup['ProxyServer'] is not None:
                    winreg.SetValueEx(key, 'ProxyServer', 0, winreg.REG_SZ, self._backup['ProxyServer'])
                else:
                    try:
                        winreg.DeleteValue(key, 'ProxyServer')
                    except Exception:
                        pass

            self._refresh_windows_proxy()
            return True
        except Exception as e:
            print(f"Failed to restore system proxy: {e}")
            return False

    def is_proxy_enabled(self):
        """检查是否启用了代理"""
        if not self._is_windows:
            return False

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.proxy_key) as key:
                value = winreg.QueryValueEx(key, "ProxyEnable")
                return bool(value[0])
        except Exception:
            return False


if __name__ == '__main__':
    config = ProxyConfig()
    print("Current system proxy enabled:", config.is_proxy_enabled())
