# 架构说明

## 总体架构

系统采用 Vue 3 + FastAPI + SQLite 的轻量化单体架构。RAG、规则引擎、审查器和报告导出均通过后端模块边界隔离，默认可以在没有外部模型和 Chroma 服务的情况下运行本地演示。

```mermaid
flowchart LR
    U[用户浏览器<br/>Vue 3 工作台] -->|JWT / multipart| API[FastAPI API 层]
    API --> AUTH[JWT 鉴权与角色策略]
    API --> CONTRACT[合同服务<br/>上传 / 解析 / 详情 / 版本比对]
    API --> ADMIN[管理员服务<br/>规则 / 知识库 / 用户 / 系统参数]
    API --> REVIEW[复核服务<br/>逐条判定 / 整体完成]

    CONTRACT --> PARSER[document_parser<br/>PDF / DOCX / TXT -> 文本 -> 条款]
    CONTRACT --> STATE[合同状态机<br/>上传中 -> 解析中 -> 待审查<br/>-> AI审查完成 -> 待法务复核 -> 复核完成]
    REVIEW --> STATE
    CONTRACT --> ENGINE[审查编排器]
    ENGINE --> RULE[rule_engine<br/>keyword / regex / num]
    ENGINE --> RAG[rag_engine<br/>启用知识库检索]
    ENGINE --> AUDIT[llm_audit<br/>确定性基线 / 可替换模型适配]
    RAG --> CHROMA[(Chroma<br/>可选向量服务)]
    RAG --> SQLITE[(SQLite 关键词降级)]
    RULE --> DB[(SQLite 数据库)]
    RAG --> DB
    CONTRACT --> DB
    ADMIN --> DB
    REVIEW --> DB
    REVIEW --> EXPORT[report_export<br/>PDF / Markdown]
    EXPORT --> DL[浏览器下载审查报告]
```

## 一次审查时序

```mermaid
sequenceDiagram
    actor User as 用户
    participant Web as Vue 工作台
    participant API as FastAPI
    participant Parser as 文档解析器
    participant Rule as 规则引擎
    participant RAG as RAG 检索
    participant DB as SQLite

    User->>Web: 选择 PDF / DOCX
    Web->>API: POST /api/contracts/upload + JWT
    API->>DB: 写入上传中与状态日志
    API->>Parser: 校验签名、解压结构并抽取文本
    Parser-->>API: 原文与结构化条款
    API->>DB: 保存条款，状态改为待审查
    User->>Web: 运行 AI 审查
    Web->>API: POST /api/contracts/{id}/audit
    API->>Rule: 匹配启用的业务规则
    API->>RAG: 检索启用的法条/企业规范
    RAG-->>API: 带来源 ID 的依据
    API->>DB: 仅保存有来源的风险结果
    API-->>Web: 风险、依据、修改建议
    User->>Web: 逐条选择属实/不属实
    Web->>API: POST /api/contracts/{id}/review/complete
    API->>DB: 保存意见并记录复核完成状态
```

## 状态与数据边界

```mermaid
stateDiagram-v2
    [*] --> 上传中
    上传中 --> 解析中
    解析中 --> 待审查: 解析成功
    解析中 --> 解析失败: 文件损坏/解析异常
    待审查 --> AI审查完成: 规则+RAG执行
    AI审查完成 --> 待法务复核: 存在风险
    AI审查完成 --> 复核完成: 无风险
    待法务复核 --> 法务复核中: 开始逐条复核
    法务复核中 --> 复核完成: 全部风险完成判定
    解析失败 --> 解析中: 重新解析
```

每次状态变更写入 `contract_status_log`，包含合同、状态、操作人和时间。`uploader` 只能查询自己的合同；`legal_reviewer` 可以查看全部合同并执行复核；`admin` 额外拥有 `/api/admin/*` 权限。管理员接口通过 FastAPI 路由依赖统一拦截，不能依赖前端隐藏菜单来保证安全。

## 模块职责

| 模块 | 职责 | 可替换点 |
| --- | --- | --- |
| `backend/main.py` | API、JWT、角色校验、状态编排、静态前端 | 可拆分为多个服务 |
| `backend/document_parser` | PDF/DOCX/TXT 解析、条款抽取 | OCR、版面分析 |
| `backend/rule_engine` | 关键词、正则、数值规则匹配 | Drools、规则平台 |
| `backend/rag_engine` | Chroma 检索与 SQLite 降级 | Milvus、pgvector |
| `backend/llm_audit` | 确定性基线审查、来源门禁、模糊项拦截 | Qwen / OpenAI 兼容服务 |
| `backend/report_export` | PDF、Markdown 报告和免责声明 | 企业模板、对象存储 |
| `frontend/app.js` | 登录、路由、管理台、上传与复核交互 | Vue Router、组件库 |

## 目录与运行边界

- `data_storage/`：SQLite、上传文件和运行时数据，只在本地或挂载卷保存，不提交 Git。
- `knowledge_base/`：首次启动导入的演示规则和知识库 JSON。
- `docs/schema.sql`：与现有单数表名一致的完整建表脚本。
- `docs/demo_seed.sql`：bcrypt 演示账号、规则、知识库和系统参数初始化数据。
- `frontend/assets/contract-review-logo.svg`：导航栏与 favicon 使用的项目 Logo。

默认部署由一个 Uvicorn 进程在 `8082` 提供 API 与前端静态文件；开发脚本额外启动 Vite，默认使用 `5173`，若端口被占用则自动顺延并通过 `--port` 传入实际端口以支持热更新。
