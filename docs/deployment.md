# Word2Video 本地部署文档

## 1. 文档目标

本文档用于说明 Word2Video PC Web 应用的本地部署方案。

部署要求：

- 后端使用 Python FastAPI。
- 采用本地部署，不依赖云服务器。
- 前端使用 Vue。
- 数据库使用本地 SQLite。
- 对象存储使用本地文件系统。

当前仓库仍处于设计阶段，尚未创建前端和后端工程代码。本文档先定义推荐目录结构、运行方式、环境变量、构建部署流程和备份策略，后续代码落地后可补充具体脚本。

## 2. 总体架构

```text
用户浏览器
  ↓
Vue PC Web 前端
  ↓ HTTP API
FastAPI 后端服务
  ├── SQLite 本地数据库
  ├── 本地对象存储目录
  └── AI 能力适配层
```

### 2.1 组件说明

| 组件 | 技术方案 | 说明 |
| --- | --- | --- |
| 前端 | Vue 3 + TypeScript + Vite | PC 工作台界面 |
| 后端 | Python + FastAPI | API、业务流程、文件上传下载 |
| 数据库 | SQLite | 保存项目、知识图谱、实体、分帧和资源元数据 |
| 对象存储 | 本地文件系统 | 保存用户上传参考图、AI 生成图、导出素材包 |
| 部署方式 | 本地单机部署 | 适合个人电脑、工作站或内网服务器 |

## 3. 推荐项目目录结构

```text
word2video/
├── frontend/
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── vite.config.ts
│   ├── src/
│   └── dist/
├── backend/
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── core/
│   │   ├── models/
│   │   ├── schemas/
│   │   ├── services/
│   │   └── storage/
│   └── alembic/
├── data/
│   ├── word2video.db
│   ├── uploads/
│   ├── generated/
│   ├── exports/
│   └── temp/
├── docs/
│   ├── page-function-design.md
│   └── deployment.md
└── scripts/
    ├── start-dev.ps1
    ├── start-prod.ps1
    └── backup.ps1
```

### 3.1 data 目录说明

| 目录 | 用途 |
| --- | --- |
| `data/word2video.db` | SQLite 数据库文件 |
| `data/uploads/` | 用户上传的实体参考图片 |
| `data/generated/` | AI 生成的实体模型图片 |
| `data/exports/` | 导出的素材包 |
| `data/temp/` | 临时文件、处理中间产物 |

`data/` 目录必须加入备份策略。正式运行时不建议删除该目录。

## 4. 本地端口规划

| 服务 | 默认端口 | 说明 |
| --- | --- | --- |
| Vue 开发服务 | `5173` | 本地前端开发 |
| FastAPI 开发服务 | `8000` | 本地后端 API |
| 生产访问入口 | `8000` 或 `8080` | 可由 FastAPI 直接托管前端静态文件，也可由 Nginx 托管 |

首版推荐：

- 开发环境：Vue 和 FastAPI 分开启动。
- 本地生产环境：FastAPI 托管 Vue 构建产物，减少部署组件。

## 5. 环境变量

建议在后端目录创建 `.env` 文件：

```bash
APP_NAME=Word2Video
APP_ENV=local
APP_HOST=127.0.0.1
APP_PORT=8000

DATABASE_URL=sqlite:///../data/word2video.db

STORAGE_ROOT=../data
UPLOAD_DIR=../data/uploads
GENERATED_DIR=../data/generated
EXPORT_DIR=../data/exports
TEMP_DIR=../data/temp

FRONTEND_DIST_DIR=../frontend/dist

CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

AI_GRAPH_PROVIDER=mock
AI_IMAGE_PROVIDER=mock
```

前端目录建议创建 `.env.local`：

```bash
VITE_APP_NAME=Word2Video
VITE_API_BASE_URL=http://127.0.0.1:8000/api
VITE_ASSET_BASE_URL=http://127.0.0.1:8000/storage
```

### 5.1 敏感信息要求

如果后续接入第三方 AI 服务，API Key 只允许放在后端 `.env` 中，不允许写入前端 `.env.local`。

不允许暴露到前端的内容包括：

- AI 服务 API Key。
- 本地管理密钥。
- 数据库文件路径以外的系统敏感路径。
- 任何用户私密文件路径。

## 6. 前端本地开发

前端使用 Vue 3 + TypeScript + Vite。

### 6.1 安装依赖

```bash
cd frontend
pnpm install
```

### 6.2 启动开发服务

```bash
pnpm dev
```

默认访问地址：

```text
http://localhost:5173
```

### 6.3 构建前端

```bash
pnpm build
```

构建产物目录：

```text
frontend/dist/
```

## 7. 后端本地开发

后端使用 Python FastAPI。

### 7.1 创建虚拟环境

Windows PowerShell：

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
```

### 7.2 安装依赖

```bash
pip install -r requirements.txt
```

建议首版依赖：

```text
fastapi
uvicorn[standard]
python-dotenv
sqlalchemy
alembic
pydantic
pydantic-settings
python-multipart
aiofiles
```

### 7.3 初始化本地目录

```bash
mkdir -p ../data/uploads ../data/generated ../data/exports ../data/temp
```

Windows PowerShell：

```powershell
New-Item -ItemType Directory -Force ..\data\uploads, ..\data\generated, ..\data\exports, ..\data\temp
```

### 7.4 初始化 SQLite

如果使用 Alembic 管理数据库迁移：

```bash
alembic upgrade head
```

如果首版先由应用自动建表，则启动 FastAPI 时检查并创建：

```text
data/word2video.db
```

### 7.5 启动后端开发服务

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API 文档地址：

```text
http://127.0.0.1:8000/docs
```

## 8. 本地生产部署

本地生产部署推荐使用 FastAPI 托管前端静态产物，整体只启动一个服务。

### 8.1 构建前端

```bash
cd frontend
pnpm install
pnpm build
```

### 8.2 安装后端依赖

```bash
cd ../backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 8.3 初始化数据目录

```powershell
New-Item -ItemType Directory -Force ..\data\uploads, ..\data\generated, ..\data\exports, ..\data\temp
```

### 8.4 启动生产服务

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

本地访问地址：

```text
http://127.0.0.1:8000
```

如需在局域网内访问，可将 host 改为：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

局域网部署时，需要确认防火墙已放行对应端口。

## 9. FastAPI 静态文件托管建议

后端可以同时提供 API、对象文件访问和前端页面。

推荐路由：

| 路由 | 用途 |
| --- | --- |
| `/api/*` | 后端业务接口 |
| `/storage/uploads/*` | 用户上传参考图 |
| `/storage/generated/*` | AI 生成实体图 |
| `/storage/exports/*` | 导出素材包下载 |
| `/` | Vue 前端页面 |

FastAPI 静态挂载示例：

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Word2Video")

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIST_DIR = BASE_DIR / "frontend" / "dist"

app.mount("/storage/uploads", StaticFiles(directory=DATA_DIR / "uploads"), name="uploads")
app.mount("/storage/generated", StaticFiles(directory=DATA_DIR / "generated"), name="generated")
app.mount("/storage/exports", StaticFiles(directory=DATA_DIR / "exports"), name="exports")

if FRONTEND_DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        index_file = FRONTEND_DIST_DIR / "index.html"
        return FileResponse(index_file)
```

注意：实际代码中应确保 `/api` 路由先注册，避免被前端兜底路由拦截。

## 10. SQLite 部署规范

SQLite 数据库文件建议固定为：

```text
data/word2video.db
```

### 10.1 数据库存储内容

SQLite 保存结构化元数据：

- 项目信息。
- 原始剧本。
- 知识图谱节点和关系。
- 实体对象。
- 实体图片元数据。
- 分帧描述。
- 帧与实体图片的关联关系。
- 导出记录。

### 10.2 不建议存入 SQLite 的内容

以下内容应保存为本地文件，并在 SQLite 中保存路径或 URL：

- 用户上传图片。
- AI 生成图片。
- 导出压缩包。
- 图谱截图。
- 大型临时文件。

### 10.3 并发限制

SQLite 适合本地单机和少量用户场景。若后续需要多人并发使用、远程访问或高频写入，应考虑迁移到 PostgreSQL。

## 11. 本地对象存储规范

对象存储根目录：

```text
data/
```

推荐文件路径规则：

```text
data/uploads/{projectId}/{entityId}/{fileName}
data/generated/{projectId}/{entityId}/{imageId}.png
data/exports/{projectId}/{exportId}.zip
data/temp/{taskId}/
```

### 11.1 上传限制

首版建议限制：

| 类型 | 限制 |
| --- | --- |
| 图片格式 | `.png`、`.jpg`、`.jpeg`、`.webp` |
| 单张图片大小 | 不超过 10 MB |
| 单个实体参考图数量 | 默认不超过 10 张 |
| 单个项目导出包大小 | 默认不超过 1 GB |

### 11.2 文件访问

前端通过后端 URL 访问文件：

```text
http://127.0.0.1:8000/storage/uploads/...
http://127.0.0.1:8000/storage/generated/...
http://127.0.0.1:8000/storage/exports/...
```

不要让前端直接读取本地绝对路径。

## 12. 一键启动脚本建议

### 12.1 开发环境启动脚本

建议创建 `scripts/start-dev.ps1`：

```powershell
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd frontend; pnpm dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd backend; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
```

### 12.2 本地生产启动脚本

建议创建 `scripts/start-prod.ps1`：

```powershell
cd frontend
pnpm build

cd ..\backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## 13. 备份与恢复

本地部署最重要的是保护 `data/` 目录。

### 13.1 备份内容

必须备份：

- `data/word2video.db`
- `data/uploads/`
- `data/generated/`
- `data/exports/`

可选备份：

- `.env`
- 前端构建产物 `frontend/dist/`
- 运行日志目录

### 13.2 备份脚本示例

建议创建 `scripts/backup.ps1`：

```powershell
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = "backups\word2video-$timestamp"

New-Item -ItemType Directory -Force $backupDir
Copy-Item -Recurse -Force data "$backupDir\data"

Compress-Archive -Path "$backupDir\*" -DestinationPath "$backupDir.zip"
Write-Host "Backup created: $backupDir.zip"
```

### 13.3 恢复方式

1. 停止 FastAPI 服务。
2. 将当前 `data/` 目录重命名为 `data.bak`。
3. 解压备份包。
4. 将备份中的 `data/` 复制回仓库根目录。
5. 启动 FastAPI 服务。
6. 打开页面检查项目列表、图片和导出文件是否正常。

## 14. 日志与运行检查

### 14.1 日志建议

后端建议记录：

- 服务启动和关闭。
- 剧本解析任务。
- 知识图谱生成任务。
- 实体图片生成任务。
- 文件上传和导出任务。
- API 异常和耗时。

日志目录建议：

```text
data/logs/
```

### 14.2 健康检查接口

建议后端提供：

```text
GET /api/health
```

返回示例：

```json
{
  "status": "ok",
  "database": "ok",
  "storage": "ok"
}
```

健康检查应确认：

- SQLite 文件可读写。
- `data/uploads` 可写。
- `data/generated` 可写。
- `data/exports` 可写。

## 15. 上线前检查清单

### 15.1 前端检查

- Vue 页面可正常打开。
- 页面刷新不会出现 404。
- API 地址指向本地 FastAPI。
- 剧本输入、知识图谱、实体、图片、分帧和导出页面入口完整。
- 1366px 及以上 PC 屏幕布局正常。

### 15.2 后端检查

- FastAPI 服务可启动。
- `/api/health` 返回正常。
- `/docs` 可访问。
- SQLite 数据库文件已创建。
- 本地对象存储目录已创建。
- 文件上传、访问、删除流程正常。

### 15.3 数据检查

- 项目可创建和读取。
- 知识图谱数据可保存。
- 实体对象可保存和更新。
- 实体图片元数据和本地文件路径一致。
- 分帧描述可保存。
- 导出素材包可生成并下载。

### 15.4 安全检查

- 前端不包含 AI 服务 API Key。
- 后端 `.env` 不提交到 Git。
- 上传文件有格式和大小限制。
- 文件访问不暴露本机绝对路径。
- 局域网访问时防火墙规则明确。

## 16. 后续待补充

- 实际 Vue 工程目录和依赖版本。
- 实际 FastAPI 目录和依赖版本。
- SQLite 表结构和迁移脚本。
- 本地对象存储清理策略。
- AI 图片生成服务接入方式。
- Windows 服务化启动方式。
- macOS/Linux systemd 启动方式。
