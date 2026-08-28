# 部署说明

## 本地一键启动

前置安装 Python 3.10+、Node.js（包含 npm）。在项目根目录运行：

```text
Windows：双击 start.bat
Linux/macOS：chmod +x start.sh && ./start.sh
```

脚本会创建 `venv`、安装 `requirements.txt` 和 `frontend/package.json` 依赖，检查 `8082`/`5173` 端口，启动 FastAPI 与 Vite，并自动打开浏览器。关闭所有前端页面后，运行时心跳会让脚本清理两个进程。

## Docker 演示

```bash
cp .env.example .env
# 编辑 .env，至少替换 JWT_SECRET
docker compose up --build
```

访问 `http://localhost:8082`。`data_storage` 和 `chroma_db` 通过 Compose volume 持久化。默认 `CHROMA_ENABLED=false`，未部署 Chroma 时使用 SQLite 关键词检索。

## 环境变量

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `JWT_SECRET` | 无安全默认值 | JWT 签名密钥，生产必须替换 |
| `CONTRACT_REVIEW_DB` | `./data_storage/contract_review.db` | SQLite 路径 |
| `MAX_UPLOAD_MB` | `20` | 文件大小上限 |
| `CHROMA_ENABLED` | `false` | 是否启用 Chroma |
| `LLM_PROVIDER` | `local` | 审查器提供方，默认确定性基线 |
| `QWEN_MODEL_PATH` | `./models/Qwen2.5-7B-Instruct` | 私有模型路径预留 |

系统设置页中的 Chroma、LLM、上传路径和风险阈值会保存到 `system_config` 表；上传路径只能是项目内相对路径。

## 生产部署建议

- 使用 HTTPS 反向代理和受限 CORS，不直接暴露 Uvicorn 开发监听。
- 将 `data_storage` 放到加密卷或私有对象存储，并配置备份、恢复演练和保留期限。
- 接入杀毒扫描、DLP、速率限制、审计日志、告警和登录失败锁定。
- 使用密钥管理服务托管 JWT、LLM 和向量服务凭据；不要把 `.env` 加入 Git。
- 替换所有演示账号密码，清理 `demo_files` 上传记录并关闭公开 Swagger。
- 上线前按 `docs/TEST_PLAN.md` 完成三角色、文件安全、幻觉治理、失败降级和成本压测验收。
