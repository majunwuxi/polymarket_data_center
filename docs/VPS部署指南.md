# Ubuntu VPS 部署指南

这份指南适用于一台可以访问互联网、使用 systemd 的 Ubuntu VPS。指南已对照代码参数检查，但尚未在真实 VPS 上实测。项目目前处于实验阶段：采集记录可能不完整，成交身份和统计口径仍需验证；它不下单，也不需要 Polymarket 密钥。以下操作不会由本项目自动执行。

## 1. 准备服务器

准备有 sudo 权限的服务器账号、Python 3.9 或更高版本、Git、SSH，以及访问 GitHub、ESPN 和 Polymarket 的网络。本示例以 `/opt/polymarket_data` 放代码，以 `/var/lib/polymarket-data` 放数据库。命令中的 GitHub 地址指向公开仓库。

登录 VPS 后执行：

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
python3 --version
sudo useradd --system --home-dir /var/lib/polymarket-data --shell /usr/sbin/nologin polymarket
sudo install -d -o polymarket -g polymarket -m 750 /var/lib/polymarket-data
sudo git clone https://github.com/majunwuxi/polymarket_data_center.git /opt/polymarket_data
sudo python3 -m venv /opt/polymarket_data/.venv
sudo /opt/polymarket_data/.venv/bin/python -m pip install -r /opt/polymarket_data/requirements.txt
```

如果账号或目录已经存在，先核对原有用途，不要覆盖。`.venv` 和数据库不会提交到 GitHub。

## 2. 配置开机启动

创建采集服务：

```bash
sudo tee /etc/systemd/system/polymarket-recorder.service >/dev/null <<'EOF'
[Unit]
Description=Polymarket NBA recorder
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=polymarket
Group=polymarket
WorkingDirectory=/opt/polymarket_data
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/polymarket_data/.venv/bin/python /opt/polymarket_data/recorder.py --db /var/lib/polymarket-data/nba_trades.sqlite3 run
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
```

创建日历服务：

```bash
sudo tee /etc/systemd/system/polymarket-dashboard.service >/dev/null <<'EOF'
[Unit]
Description=Polymarket NBA calendar dashboard
After=network.target

[Service]
Type=simple
User=polymarket
Group=polymarket
WorkingDirectory=/opt/polymarket_data
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/polymarket_data/.venv/bin/python /opt/polymarket_data/dashboard.py --db /var/lib/polymarket-data/nba_trades.sqlite3 --port 8068
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
```

启动并查看服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now polymarket-recorder.service polymarket-dashboard.service
sudo systemctl status polymarket-recorder.service polymarket-dashboard.service --no-pager
sudo journalctl -u polymarket-recorder.service -n 50 --no-pager
sudo journalctl -u polymarket-dashboard.service -n 50 --no-pager
curl http://127.0.0.1:8068/api/calendar
```

采集和维护需要时间，启动后如果显示暂无赛程，先查看采集服务日志。看采集状态：

```bash
sudo -u polymarket /opt/polymarket_data/.venv/bin/python /opt/polymarket_data/recorder.py --db /var/lib/polymarket-data/nba_trades.sqlite3 status
```

## 3. 从自己的电脑打开日历

仪表盘默认仅在 VPS 的本机地址 `127.0.0.1:8068` 监听，没有登录功能。**不要直接把它暴露到公网**。在自己的电脑上打开终端，把 `你的账号` 和 `VPS地址` 替换为实际值：

```bash
ssh -L 8068:127.0.0.1:8068 你的账号@VPS地址
```

保持这个 SSH 窗口打开，再在自己的电脑上访问 `http://127.0.0.1:8068`。如果本机 8068 已被占用，可把命令中的第一个 `8068` 换成 `18068`，然后访问 `http://127.0.0.1:18068`。SSH 连接断开后隧道也会关闭。

如果 VPS 上已按旧指南安装过日历服务，更新代码后还需编辑 `/etc/systemd/system/polymarket-dashboard.service`，把 `ExecStart` 中显式指定的旧端口改为 `8068`，然后执行 `sudo systemctl daemon-reload` 和 `sudo systemctl restart polymarket-dashboard.service`。同时更新 SSH 隧道命令；仅更新代码不会自动改写已有的 systemd 文件。

## 3B. 使用域名和 HTTPS 访问

这一节是 SSH 隧道之外的另一种访问方式。完成后，你可以在浏览器输入类似 `https://nba.example.com` 的网址。**`nba.example.com` 只是示例，必须换成你自己拥有并能设置解析的真实域名。** 当前尚未购买域名、配置 VPS 或申请证书；以下是将来部署时的操作。

### 第一步：把域名指向 VPS

在你的域名服务商的 DNS 设置页面，添加一条 A 记录：

| 项目 | 示例 |
| --- | --- |
| 主机记录 | `nba` |
| 记录类型 | `A` |
| 记录值 | 你的 VPS 公网 IPv4 地址 |

例如你拥有 `example.com`，上述记录对应的网址就是 `nba.example.com`。如果使用其他子域名，请按实际填写。如果已经有同名 A、AAAA 或 CNAME 记录，先检查并处理冲突；只有 VPS 的 IPv6 也能正常访问时才配置指向它的 AAAA 记录。等待 DNS 生效后，在 VPS 上检查解析结果：

```bash
getent ahosts nba.example.com
```

把示例域名换成自己的域名，检查返回地址是否是你的 VPS 公网地址。不同地区的 DNS 生效时间可能不同。

### 第二步：准备端口并安装 Caddy

在 VPS 服务商的安全组或云防火墙，以及服务器自身的防火墙中，允许公网访问 **TCP 80 和 443**。80 用于证书验证及跳转，443 用于 HTTPS；**8068 仍只在 VPS 本机使用，不要对公网开放**。在修改防火墙之前，确认现有 SSH 端口仍被允许，避免断开自己的管理连接。如果 80 或 443 已由其他网站占用，先确认现有服务的配置，不能直接覆盖或停掉它。

在 Ubuntu VPS 上安装 Caddy 官方稳定包：

```bash
sudo apt install --yes debian-keyring debian-archive-keyring apt-transport-https curl gnupg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

安装时如果提示已有同名文件，请先核实现有 Caddy 软件源，不要盲目覆盖。官方安装说明：[Caddy 安装文档](https://caddyserver.com/docs/install)。

### 第三步：配置访问密码和网站地址

日历本身没有登录功能。**HTTPS 只负责加密，不会自动阻止其他人访问**，因此下面示例同时设置登录账号和密码。先生成密码的加密结果：

```bash
caddy hash-password
```

按提示输入自己设置的强密码，复制输出的一整串密码哈希。不要把明文密码或哈希提交到 GitHub，也不要把它发给别人。

编辑 Caddy 配置文件：

```bash
sudo nano /etc/caddy/Caddyfile
```

如果文件里已经有其他网站配置，请保留原内容，并在末尾加入下面的站点配置；新安装且使用默认配置时，也要先确认不会影响已有服务。将 `nba.example.com` 换成真实域名，将 `dashboarduser` 换成你自己的登录名，将 `此处粘贴密码哈希` 换成上一步输出的**完整哈希**，不要输入明文密码：

```caddyfile
nba.example.com {
    basic_auth {
        dashboarduser 此处粘贴密码哈希
    }
    reverse_proxy 127.0.0.1:8068
}
```

保存后先检查配置，再重新加载服务：

```bash
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl enable --now caddy
sudo systemctl reload caddy
sudo systemctl status caddy --no-pager
```

只有检查通过才执行后面的启动或重新加载。Caddy 会把域名请求转发给本机 8068 端口；在 DNS 和网络条件满足时，自动申请并续期证书，并将 HTTP 跳转到 HTTPS。Caddy 的证书数据需要持久保存，不能随意清空其数据目录。参考：[自动 HTTPS](https://caddyserver.com/docs/automatic-https) 和 [密码保护配置](https://caddyserver.com/docs/caddyfile/directives/basic_auth)。

### 第四步：验证网址和证书

在自己的电脑浏览器打开 `https://你的真实域名`，确认浏览器显示安全连接，并使用刚设置的账号密码登录。可以在 VPS 上检查：

```bash
curl -I https://nba.example.com
sudo journalctl -u caddy -n 100 --no-pager
```

把示例域名换成真实域名。未带账号密码的请求如果返回 `401 Unauthorized`，表示登录保护生效；浏览器仍需实际测试能否登录和显示日历。证书或页面有问题时，检查 DNS 是否指向正确服务器、80/443 是否放行且未冲突、Caddy 和日历服务是否运行，以及 `journalctl` 中的错误。证书无法申请成功时不要反复无限重试，以免触发证书机构的频率限制。

## 4. 更新与备份

**定期清理会永久删除符合条件的比赛交易明细。** 目前没有在清理前自动保存长期统计；如需日后分析，请先另行备份并规划汇总。每日维护通常在北京时间 15:30 后执行，只有开赛超过 24 小时、事件关闭且所有相关市场确认结算才会清理；有疑问的数据会保留。

SQLite 可能正在使用 WAL 文件，不要只复制运行中的主数据库文件。以下命令使用 SQLite 的在线备份功能，生成一个可独立保存的备份文件。先确保备份路径可写且目标文件不存在：

```bash
sudo -u polymarket /opt/polymarket_data/.venv/bin/python -c "import sqlite3; src=sqlite3.connect('file:/var/lib/polymarket-data/nba_trades.sqlite3?mode=ro',uri=True); dst=sqlite3.connect('/var/lib/polymarket-data/backup.sqlite3'); src.backup(dst); dst.close(); src.close()"
```

使用前确认目标文件不存在，避免覆盖旧备份；完成后应把备份安全地复制到另一台机器，并定期验证能否恢复。备份不包含 VPS 服务配置。

更新程序前先备份数据库，并检查本地有无改动。示例仅在仓库没有本地改动、确认目标版本后使用：

```bash
cd /opt/polymarket_data
sudo git status --short --branch
sudo systemctl stop polymarket-recorder.service polymarket-dashboard.service
sudo git pull --ff-only
sudo /opt/polymarket_data/.venv/bin/python -m pip install -r /opt/polymarket_data/requirements.txt
sudo systemctl start polymarket-recorder.service polymarket-dashboard.service
sudo systemctl status polymarket-recorder.service polymarket-dashboard.service --no-pager
```

若更新失败，服务可能仍处于停止状态；检查报错后手动恢复。不要用 `reset --hard` 或强制推送覆盖数据。

## 5. 常见问题

- **服务无法启动**：用 `journalctl -u 服务名 -n 100 --no-pager` 查看错误，检查 Python、依赖和数据库目录权限。
- **无赛程或更新失败**：检查服务器能否访问 ESPN、Polymarket；接口或网络可能暂时不可用。状态页面中的“尚未确认开放”不等于网站市场一定关闭。
- **网页无法打开**：先在 VPS 上运行第 2 节的 `curl`，再检查本机 SSH 隧道是否保持连接、端口是否冲突。
- **数据不全或盘口为零**：本项目仍在验证采集完整性；页面只展示本地已记录的数据，不代表网站没有交易。
