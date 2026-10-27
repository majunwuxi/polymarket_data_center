# Design

## Context

现有采集器将赛程、市场和检查点保存在 SQLite；数据仍是实验性且不保证完整。

## Goals / Non-Goals

**Goals:** 按北京时间呈现日历和选中日比赛，仅展示真实数据库数据。

**Non-Goals:** 不计算投注方向统计，不部署网站，也不启动后台采集。

## Decisions

使用 Python 标准库本地只读 HTTP 服务读取 SQLite，静态 HTML/CSS/JS 展示月历和每日列表。浏览器自动刷新，数据库缺失或查询失败显示明确状态。市场按真实 `sportsMarketType` 分类，仅显示三类及采集检查点。

## Risks / Trade-offs

- [本地数据库缺少赛程或存在延迟] → 显示空状态和数据来源提示。
- [采集状态与完整性不同] → 不将市场开放描述为已完整采集。
