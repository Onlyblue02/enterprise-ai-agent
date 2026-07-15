# Changelog

本项目从 `v1.0.0` 开始记录公开版本。版本号遵循语义化版本规则。

## [1.0.1] - 2026-07-15

### Fixed

- DashScope 原生 Agent 和 LangGraph 工作流遇到临时 SSL、连接中断或超时时自动重试
- 网络重试仍失败时展示可理解的代理和网络检查提示

### Documentation

- 增加当前企业版首页和资料中心截图

## [1.0.0] - 2026-07-15

首个可演示版本，功能基线正式冻结。

### Added

- TXT、Markdown、PDF、DOCX 文档解析、切分、向量化和本地知识库管理
- 基于 DashScope Embedding、Chroma 与 Qwen 的引用式 RAG 问答
- Qwen 原生 Function Calling Agent
- 知识库、企业业务数据和受控计算工具
- LangGraph 企业经营报告工作流
- 模型质量审核、人工批准和人工修改闭环
- SQLite checkpoint 持久化与待审批任务恢复
- Agent 与工作流的流式输出和执行进度
- 运行状态、工具、节点、耗时、Token 和异常监控
- 企业风格 Streamlit 页面和完整项目 README
- 文档入库失败回滚、空文件校验和明确异常提示
- 21 项核心自动化测试

### Security

- API Key 通过 `.env` 管理，不写入源码
- 本地文档、向量库、会话、SQLite 和 checkpoint 统一存放于 `data/` 并排除提交
- 业务数据库工具不允许模型执行任意 SQL
- 计算工具不允许执行任意系统命令

### Known limitations

- 当前版本是单机求职 Demo，没有登录、多租户和角色权限
- Chroma 与 SQLite 适合本地演示，不面向高并发生产环境
- 扫描版 PDF 尚未集成 OCR
- 本地运行数据不会自动同步到云端部署环境
- 尚未建立系统化 RAG 评测集与质量基准

## 版本冻结规则

- `v1.0.x`：只接受 Bug、安全、兼容性、测试和文档修复
- `v1.1.0`：允许小型、向后兼容的功能增强
- `v2.0.0`：仅用于存在架构或数据格式不兼容的重大升级
