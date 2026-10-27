# Proposal

## Why

用户需要在 VPS 上通过域名和 HTTPS 访问现有日历，因此部署指南应说明域名解析、证书和访问保护的具体操作。

## What Changes

- 在 VPS 文档中加入域名、Caddy HTTPS、认证、续期与排障操作。
- 保留 SSH 隧道方式和本机 8068 监听，不实际部署。

## Capabilities

### New Capabilities

无。本次只说明既有应用如何部署。

### Modified Capabilities

无。

## Impact

更新部署指南，不修改应用代码或真实服务器。
