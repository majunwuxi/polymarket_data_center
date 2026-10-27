# Proposal

## Why

持续保存 NBA 市场成交，供未来按钱包和比赛项目分析，并使采集缺口可追溯。

## What Changes

- 自动发现 NBA 比赛与子市场，持续采集原始成交，保存采集进度。
- 使用公开赛程建立比赛候选，在开赛前八天开始检查 Polymarket 市场。
- 每日北京时间 15:30 执行过期比赛数据清理并压缩数据库。
- 仅采集全场胜负、全场让分和全场总分的全部盘口线，不采集其他市场交易。
- 提供重叠补采、历史分页、故障恢复与可检查状态；保留身份不确定性。
- 暂不提供投注方向统计或部署网站。

## Capabilities

### New Capabilities

- `nba-recording`: NBA 市场发现、成交记录与采集状态。

### Modified Capabilities

无。

## Impact

新增 Python 服务、SQLite 数据库、命令行及测试，依赖 Polymarket 公共接口。
