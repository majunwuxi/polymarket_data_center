# Spec Delta

## ADDED Requirements

### Requirement: 球队全名与比赛链接
系统 SHALL 以中文及英文全名显示 NBA 球队，并为两队提供到相应 Polymarket 比赛页面的链接。

#### Scenario: 已开放的比赛
- **WHEN** 日历中的比赛对应已验证的 Polymarket 事件
- **THEN** 客队和主队名称均显示中英文全名并链接到该比赛页面

#### Scenario: 市场尚未确认或球队未知
- **WHEN** 比赛事件尚未确认，或球队缩写无法识别
- **THEN** 提供候选链接并标明可能尚未开放；未知球队保留英文原名并标明中文未知
