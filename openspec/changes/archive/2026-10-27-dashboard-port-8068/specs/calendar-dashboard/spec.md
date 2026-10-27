# Spec Delta

## ADDED Requirements

### Requirement: 日历服务默认端口
日历服务 SHALL 默认仅监听本机 8068 端口，并 SHALL 支持通过参数指定其他端口。

#### Scenario: 默认启动
- **WHEN** 用户不指定端口启动日历服务
- **THEN** 服务监听本机 8068 端口

#### Scenario: 自定义端口
- **WHEN** 用户通过参数指定其他有效端口
- **THEN** 服务监听所指定的本机端口
