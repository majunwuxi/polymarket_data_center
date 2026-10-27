# calendar-dashboard Specification

## Purpose
提供基于北京时间的 NBA 比赛日历，使用户能够按日期查找已经记录的赛程并查看相关市场的采集情况和当前数据限制。

## Requirements

### Requirement: 月历与日期选择
系统 SHALL 按北京时间显示比赛月历并允许切换月份和选择日期。

#### Scenario: 查看比赛日
- **WHEN** 用户选择有赛程的日期
- **THEN** 显示该日期每场比赛的开赛时间、客队和主队

### Requirement: 显示真实采集状态
系统 SHALL 显示比赛市场开放情况及全场胜负、让分、总分的记录情况，并明确数据不保证完整。

#### Scenario: 尚无数据或读取失败
- **WHEN** 数据库不存在、当天没有比赛或读取发生错误
- **THEN** 显示清晰的状态而不是虚构数据

### Requirement: 球队全名与比赛链接
系统 SHALL 以中文及英文全名显示 NBA 球队，并为两队提供到相应 Polymarket 比赛页面的链接。

#### Scenario: 已开放的比赛
- **WHEN** 日历中的比赛对应已验证的 Polymarket 事件
- **THEN** 客队和主队名称均显示中英文全名并链接到该比赛页面

#### Scenario: 市场尚未确认或球队未知
- **WHEN** 比赛事件尚未确认，或球队缩写无法识别
- **THEN** 提供候选链接并标明可能尚未开放；未知球队保留英文原名并标明中文未知
