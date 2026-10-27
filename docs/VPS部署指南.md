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
ExecStart=/opt/polymarket_data/.venv/bin/python /opt/polymarket_data/dashboard.py --db /var/lib/polymarket-data/nba_trades.sqlite3 --port 8765
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
curl http://127.0.0.1:8765/api/calendar
```

采集和维护需要时间，启动后如果显示暂无赛程，先查看采集服务日志。看采集状态：

```bash
sudo -u polymarket /opt/polymarket_data/.venv/bin/python /opt/polymarket_data/recorder.py --db /var/lib/polymarket-data/nba_trades.sqlite3 status
```

## 3. 从自己的电脑打开日历

仪表盘默认仅在 VPS 的本机地址 `127.0.0.1:8765` 监听，没有登录功能。**不要直接把它暴露到公网**。在自己的电脑上打开终端，把 `你的账号` 和 `VPS地址` 替换为实际值：

```bash
ssh -L 8765:127.0.0.1:8765 你的账号@VPS地址
```

保持这个 SSH 窗口打开，再在自己的电脑上访问 `http://127.0.0.1:8765`。如果本机 8765 已被占用，可把命令中的第一个 `8765` 换成 `18765`，然后访问 `http://127.0.0.1:18765`。SSH 连接断开后隧道也会关闭。

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
