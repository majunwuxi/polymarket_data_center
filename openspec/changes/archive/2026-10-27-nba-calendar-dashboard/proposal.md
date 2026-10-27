# Proposal

## Why

用户需要按日历查看 NBA 比赛及记录状态，便于找到每天的比赛。

## What Changes

- 新增读取本地赛程和采集状态的中文日历仪表盘。
- 支持切换日期、查看比赛和盘口采集情况，明确空数据和错误。

## Capabilities

### New Capabilities

- `calendar-dashboard`: 按北京时间查看比赛日历和采集状态。

### Modified Capabilities

无。

## Impact

新增只读本地 HTTP 服务和页面，读取现有 SQLite 数据库，不涉及部署。
