# Proposal

## Why

用户希望比赛页面以每个盘口汇总为重点，逐条交易过于细致且不便比较。

## What Changes

- 按比赛和盘口展示结果方向的买入、卖出金额以及已记录笔数和钱包数。
- 隐藏逐笔明细并明确统计只覆盖本地记录，不能直接当作网站成交额。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `game-details`: 由逐笔交易展示改为每个盘口汇总。

## Impact

更新只读数据接口、详情页面和测试，不更改原始成交数据或采集规则。
