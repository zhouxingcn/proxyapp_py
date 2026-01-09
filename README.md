SOCKS 二次代理转发器

说明

- 该程序在本地启动一个 HTTP(S) 代理（用于设置为系统代理），将接收的请求通过上游 SOCKS 代理转发（透明转发）。
- 启动/停止时可自动设置和还原 Windows 系统代理（修改注册表并刷新设置）。

安装

1. 安装依赖：

```powershell
pip install -r requirements.txt
```

2. 在 Windows 上直接运行：

```powershell
python main.py
```

使用

- 在 GUI 中设置本地监听地址与端口（默认 localhost:8080）。
- 设置上游 SOCKS 地址与端口（默认 localhost:1080）。
- 勾选 "启用本地代理" 后点击 "启动" 将会启动转发代理；如果勾选了 "启动时设置系统代理"，程序会把系统代理设置成本地代理并在停止时还原。

注意与限制

- 依赖 PySocks（pysocks）。请确保本机已运行上游 SOCKS 服务（例如本地的 shadowsocks 或 socks5 代理）。
- 当前实现做了基本的请求重写和 Connection: close 处理，但不是完整的高性能生产级 HTTP 代理。
- 在没有安装 PySocks 时，程序会拒绝转发并返回 502 错误。

安全

- 请不要把该代理公开到互联网上，容易被滥用。仅在本地环境使用并做好访问控制。
