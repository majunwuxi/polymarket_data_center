# Proposal

## Why

球队缩写不便于识别，也无法直接进入 Polymarket 的比赛页面。用户希望用中英文全名查看比赛并快速打开原网页。

## What Changes

- 使用球队英文全名和中文名显示主客队，并提供指向对应比赛的链接。
- 市场未确认时注明候选地址可能尚未开放。
- 项目保留本地和 VPS 使用方式，不部署到 Sites。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `calendar-dashboard`: 日历展示中英文球队名和比赛链接。

## Impact

修改本地只读接口、页面和测试，不改变原始赛程或交易记录。
