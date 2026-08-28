# 部署

本地运行见 README。私有化部署：复制 `.env.example` 为 `.env`，至少修改 `JWT_SECRET`，然后执行 `docker compose up --build -d`。生产环境建议将 `data_storage` 挂载至加密磁盘，并将对象存储接入文件适配器；反向代理仅暴露 HTTPS。
