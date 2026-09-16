# Word2Video

Word2Video 是一个本地部署的 PC Web 应用，用于把文字剧本整理成 AI 视频生产素材包。

首版能力：

- 输入文字剧本并创建项目。
- 使用 FastAPI mock 解析剧本，生成知识图谱和实体对象。
- 为人物、物品、场景等实体生成本地 SVG 模型参考图。
- 上传用户自己的实体参考图片。
- 生成视频分帧描述并关联实体参考图。
- 导出包含 `manifest.json`、原始剧本、分帧提示词和图片的 ZIP 素材包。

## 技术栈

- 前端：Vue 3 + TypeScript + Vite
- 后端：Python + FastAPI
- 数据库：SQLite
- 对象存储：本地 `data/` 目录

## 本地开发

启动后端：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

启动前端：

```powershell
cd frontend
pnpm install
pnpm dev
```

访问：

```text
http://127.0.0.1:5173
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

## 本地生产运行

```powershell
.\scripts\start-prod.ps1
```

访问：

```text
http://127.0.0.1:8000
```

## 文档

- [页面功能设计](docs/page-function-design.md)
- [本地部署文档](docs/deployment.md)
