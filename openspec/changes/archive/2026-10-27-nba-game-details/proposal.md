# Proposal

## Why

用户需要从比赛日历查看每场比赛的具体盘口与钱包成交，数据采集开始后即可呈现真实记录。

## What Changes

- 新增比赛详情页及只读接口，展示全场胜负、让分和总分盘口与分页交易明细。
- 显示数据尚未采集、查询失败和采集完整性限制，不虚构统计。

## Capabilities

### New Capabilities

- `game-details`: 单场 NBA 比赛的盘口、钱包成交与记录状态。

### Modified Capabilities

- `calendar-dashboard`: 从日历进入本项目的比赛详情页。

## Impact

修改本地仪表盘和只读 HTTP 接口；不改变采集、清理或交易数据。
