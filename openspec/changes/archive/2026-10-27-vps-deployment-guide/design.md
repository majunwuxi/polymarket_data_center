# Design

## Context

采集器与 dashboard 是独立进程，dashboard 仅监听本机；数据库保存在 Git 忽略的文件中。

## Goals / Non-Goals

**Goals:** 说明单机 Ubuntu 使用 systemd 运行、SSH 隧道查看、备份与问题排查。

**Non-Goals:** 不执行实际部署，不保证历史数据完整或自动归档。

## Decisions

以专用系统账户运行，数据库放独立目录；SSH 隧道连接本机服务。提供 SQLite 在线备份说明以避免忽略 WAL。

## Risks / Trade-offs

- [自动清理永久删除明细] → 部署前说明并给出备份方法。
- [远程仓库公开] → 不提交数据库、虚拟环境和凭据。
