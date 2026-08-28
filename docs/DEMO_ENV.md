# 演示环境

## 环境组成

| 项目 | 默认值 |
| --- | --- |
| 后端 | FastAPI + Uvicorn，默认 `http://localhost:8082`（占用时自动顺延） |
| 前端开发服务 | Vue 3 + Vite，默认 `http://localhost:5173`（占用时自动顺延） |
| 数据库 | 项目根目录 `data_storage/contract_review.db` |
| 文件存储 | `data_storage/contract_files/` |
| 向量检索 | `CHROMA_ENABLED=false` 时使用 SQLite 降级；可选 Chroma |
| 演示文件 | `demo_files/sample_risky_contract.txt`、`sample_compliant_contract.txt` |

## 启动

在项目根目录执行：

```text
Windows：双击 start.bat
Linux/macOS：chmod +x start.sh && ./start.sh
```

脚本会检查 Python 3.10+、Node.js 和依赖，并从默认端口 `8082`/`5173` 开始逐个探测；端口被占用时自动顺延到首个可用端口。没有 `.env` 时复制 `.env.example`。启动成功后自动打开实际后端地址（默认 `http://localhost:8082`），控制台同时打印实际前端端口，并提示部分业务接口仍可能返回 404。关闭所有前端页面后，心跳检测会停止前后端进程。

## 演示账号

| 账号 | 密码 | 角色 | 演示重点 |
| --- | --- | --- | --- |
| `admin` | `Admin123!` | 管理员 | 系统设置、规则/知识库/用户维护 |
| `legal` | `legal123` | 法务审核员 | 查看全部合同、逐条复核和导出报告 |
| `uploader` | `uploader123` | 上传人员 | 上传合同，仅查看本人合同 |

首次启动会自动创建账号、演示项目、规则和知识库。数据库中的密码是 bcrypt 哈希；演示环境上线前应立即替换这些密码。

## 推荐演示路径

1. 使用 `uploader` 登录，在首页下方上传区选择 `sample_risky_contract.txt`，查看上传中、解析中和待审查状态；顶部快捷弹窗用于演示正式 PDF/DOCX 上传。
2. 运行 AI 审查，查看付款、违约和缺失条款风险；展开依据确认规则 ID 或知识库编号。
3. 使用 `legal` 登录，进入合同详情，在原始全文和结构化条款间切换，逐条选择属实/不属实并提交复核。
4. 使用 `admin` 登录，新增一条关键词规则和一条企业规范知识库，立即重新审查验证生效；再禁用条目验证 RAG 不再读取。
5. 在“版本比对”选择两个合同版本，验证新增、删除、修改三种颜色标记；在“系统参数”保存 Chroma 和阈值配置。

## 演示重置

停止服务后，可备份并删除本地 `data_storage/contract_review.db` 与 `data_storage/contract_files/`，再次运行脚本会重新创建演示数据库。该操作会删除本地演示记录，生产环境不得直接执行。

## 演示边界

- 只使用 `demo_files/` 中的非敏感样例，禁止上传真实商业涉密合同。
- 这是用于架构和交互验证的演示环境，不是生产合规承诺。
- 报告中的 AI 结论必须经过法务人工复核，不能直接作为法律意见。
