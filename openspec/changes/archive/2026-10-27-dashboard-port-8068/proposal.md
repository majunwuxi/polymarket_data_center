# Proposal

## Why

用户指定日历页面使用 8068 端口，需要同步调整程序默认配置和部署指南，避免访问错误端口。

## What Changes

- 仪表盘默认监听端口更改为 8068，仍允许通过命令行指定其他端口。
- 更新本地访问及 VPS 服务和 SSH 隧道示例。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `calendar-dashboard`: 定义日历服务的默认端口。

## Impact

本地仪表盘启动参数和部署文档发生变化；现有服务需重启并更新配置。
