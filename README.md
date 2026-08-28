# contract-review-assistant

合同智能审查助手是一个面向法务团队的垂直行业 RAG + Agent + 规则引擎工作台。它将 PDF / DOCX 文档解析、条款结构化、企业规则校验、带来源的风险输出和人工复核串成可追溯闭环。

> **免责声明：本系统为 AI 辅助工具，输出结果不具备法律效力，不能替代专业法务人员审核；正式业务务必经过法务人工复核，禁止直接使用 AI 输出作为法律依据。请勿上传真实商业涉密合同到演示环境。**

## 核心能力

- PDF、DOCX、TXT 解析与甲乙方、付款、违约、保密、终止、争议、赔偿上限、知识产权条款抽取（扫描件 OCR 预留扩展点）。
- RAG 知识库检索（民法典样例法条 + 企业规范）与硬性规则引擎（关键词、正则、数值比较）。
- 来源锁定：风险必须携带法条 ID 或企业规则 ID；无法检索到依据时拦截结论并提示人工审阅。
- 法务复核状态机、合同版本列表、条款级差异比对、带底部免责水印的 PDF / Markdown 报告。
- 合同详情双栏工作台：原始文档/结构化条款预览、规则与知识库依据绑定、逐条属实性判定、整体复核提交及状态时间线。
- JWT 鉴权、上传者数据隔离、失败降级提示。
- 管理员系统设置模块，支持维护审查规则、知识库、账号角色与系统参数；菜单仅 `admin` 角色可见，全部 `/api/admin/*` 接口同步执行服务端角色鉴权。

## 快速开始

前置依赖：Python 3.10+、Node.js（包含 npm）。一键脚本会自动创建根目录下的 `venv`、安装后端和前端依赖、启动 FastAPI 与 Vue 3，并打开 [http://localhost:8082](http://localhost:8082)。

Windows：直接双击项目根目录的 `start.bat`。

Linux / macOS：

```bash
chmod +x start.sh
./start.sh
```

首次运行如果根目录没有 `.env`，脚本会提示并自动复制 `.env.example`；正式使用前请修改其中的 `JWT_SECRET`。如果 `8082` 或前端开发端口 `5173` 已被占用，脚本会停止并给出中文错误信息。关闭所有由脚本打开的前端页面后，页面心跳会在短暂宽限期内失效，脚本随后自动关闭前端和后端进程并释放两个端口；普通刷新不会误关服务。

控制台会打印访问地址和实现状态。**本项目已完成完整架构设计，部分业务功能仍待编码实现，因此部分接口可能返回 404。**

演示账号：`uploader / uploader123`、`legal / legal123`、`admin / Admin123!`。首次启动自动创建 SQLite 数据库与样例知识库。

角色权限：`uploader` 仅可查看本人上传的合同且不能执行法务复核；`legal_reviewer` 可查看全部合同并复核；`admin` 拥有全部业务权限与系统设置权限。非管理员访问 `/system-settings` 会被前端引导至 403 页面，所有 `/api/admin/*` 请求仍由后端独立返回 403。

`demo_files/` 内提供可复制文本的风险样例和合规样例，禁止上传真实涉密合同到演示环境。

## API 入口

登录 `POST /api/auth/login`；合同上传 `POST /api/contracts/upload?project_id=1`；审查 `POST /api/contracts/{id}/audit`；报告 `GET /api/contracts/{id}/report?format=pdf|md`；版本比对 `POST /api/contracts/compare?old_id=1&new_id=2`。管理员规则、知识库、用户和参数接口统一位于 `/api/admin/*`。完整交互文档启动后见 `/docs`。

## 数据库扩展

管理模块复用现有 `user`、`business_rule` 和 `knowledge_item` 表，仅新增以下系统配置表：

```sql
CREATE TABLE system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    desc TEXT NOT NULL DEFAULT ''
);
```

完整建表脚本见 `docs/schema.sql`，bcrypt 演示账号与规则/知识库初始化数据见 `docs/demo_seed.sql`。项目延续已有单数表名：需求中的 `users / contracts / contract_risk / review_rule / knowledge_base` 分别对应 `user / contract / audit_result / business_rule / knowledge_item`。

## 架构与安全

前端上传 -> 上传中 -> 解析中 -> 待审查 -> AI 审查完成 -> 待法务复核 -> 复核完成 -> 报告导出。每次状态变化记录操作人和时间。当前默认审查器为可测试的确定性基线，Qwen2.5-7B 可在 `llm_audit/` 后接入，不改变 API 契约。知识库在新增、修改、禁用或删除后自动同步 Chroma；`.env` 中 `CHROMA_ENABLED=false` 时使用 SQLite 关键词检索降级。文件按用户绑定，上传大小限制 20MB，并校验扩展名、PDF 签名、DOCX 结构及解压体积；路径使用随机前缀和项目内相对路径，新建与重置的密码使用 bcrypt 哈希存储。

## 快速改造

替换 `knowledge_base/`、规则集与审查 prompt 即可改造成智能客服、销售助手或数据分析助手；底层鉴权、文件权限、RAG 检索、人工复核和报告能力可以复用。对象存储可在 `S3_ENDPOINT` 等环境变量配置后接入存储适配器。

## 项目结构

`backend/` 为 FastAPI、解析、RAG、规则、审查和导出模块；`frontend/` 为 Vue 3 工作台，正式 Logo 位于 `frontend/assets/contract-review-logo.svg`；`knowledge_base/` 为初始化数据；`docs/` 为架构、部署、安全和场景改造说明。

## 成本与部署

默认不依赖外部 LLM，适合本地演示；私有化 Qwen2.5-7B 运行时主要成本是模型显存。SQLite、合同文件和报告均落在 `data_storage/`，向量库目录为 `chroma_db/`。可使用 `docker compose up --build` 暴露 `8082` 端口。

## 简历项目亮点

构建可审计的合同 AI 审查闭环：以来源门禁治理 LLM 幻觉，以规则引擎承载业务约束，以权限和人工复核保证生产可用性，并保留客服、销售和数据分析场景的低成本迁移路径。
