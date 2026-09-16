from __future__ import annotations

import json
import re
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")


class Settings(BaseSettings):
    app_name: str = "Word2Video"
    app_env: str = "local"
    database_url: str = "sqlite:///../data/word2video.db"
    storage_root: str = "../data"
    upload_dir: str = "../data/uploads"
    generated_dir: str = "../data/generated"
    export_dir: str = "../data/exports"
    temp_dir: str = "../data/temp"
    frontend_dist_dir: str = "../frontend/dist"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    ai_graph_provider: str = "mock"
    ai_image_provider: str = "mock"

    class Config:
        env_file = BACKEND_DIR / ".env"
        env_file_encoding = "utf-8"


settings = Settings()


def resolve_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = BACKEND_DIR / path
    return path.resolve()


DATA_DIR = resolve_path(settings.storage_root)
UPLOAD_DIR = resolve_path(settings.upload_dir)
GENERATED_DIR = resolve_path(settings.generated_dir)
EXPORT_DIR = resolve_path(settings.export_dir)
TEMP_DIR = resolve_path(settings.temp_dir)
FRONTEND_DIST_DIR = resolve_path(settings.frontend_dist_dir)


def database_path() -> Path:
    prefix = "sqlite:///"
    if not settings.database_url.startswith(prefix):
        raise RuntimeError("Only sqlite:/// DATABASE_URL is supported for local deployment.")
    raw = settings.database_url.removeprefix(prefix)
    return resolve_path(raw)


DB_PATH = database_path()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_directories() -> None:
    for directory in [DATA_DIR, UPLOAD_DIR, GENERATED_DIR, EXPORT_DIR, TEMP_DIR]:
        directory.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_directories()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                script TEXT NOT NULL,
                content_type TEXT,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS graph_nodes (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                source_text TEXT,
                entity_id TEXT,
                x REAL NOT NULL DEFAULT 0,
                y REAL NOT NULL DEFAULT 0,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS graph_edges (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                source_node_id TEXT NOT NULL,
                target_node_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                description TEXT,
                source_text TEXT,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                description TEXT NOT NULL,
                visual_description TEXT,
                prompt TEXT,
                status TEXT NOT NULL,
                main_image_id TEXT,
                occurrence_count INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS entity_images (
                id TEXT PRIMARY KEY,
                entity_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                image_url TEXT NOT NULL,
                file_path TEXT NOT NULL,
                prompt TEXT NOT NULL,
                reference_image_url TEXT,
                is_main INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS frames (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                frame_index INTEGER NOT NULL,
                source_text TEXT NOT NULL,
                description TEXT NOT NULL,
                camera TEXT,
                mood TEXT,
                entity_ids TEXT NOT NULL,
                reference_image_ids TEXT NOT NULL,
                prompt TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS exports (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                file_url TEXT NOT NULL,
                file_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            """
        )


class ProjectCreate(BaseModel):
    title: str | None = None
    script: str = Field(min_length=20)
    content_type: str | None = None


class EntityUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    description: str | None = None
    visual_description: str | None = None
    prompt: str | None = None
    status: str | None = None
    main_image_id: str | None = None


class EntityImageCreate(BaseModel):
    prompt: str | None = None


class FrameUpdate(BaseModel):
    description: str | None = None
    camera: str | None = None
    mood: str | None = None
    entity_ids: list[str] | None = None


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def list_rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_project(project_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    project = row_to_dict(row)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["entity_count"] = scalar("SELECT COUNT(*) FROM entities WHERE project_id = ?", (project_id,))
    project["completed_entity_image_count"] = scalar(
        "SELECT COUNT(*) FROM entities WHERE project_id = ? AND main_image_id IS NOT NULL",
        (project_id,),
    )
    project["frame_count"] = scalar("SELECT COUNT(*) FROM frames WHERE project_id = ?", (project_id,))
    return project


def scalar(query: str, params: tuple[Any, ...] = ()) -> int:
    with connect() as conn:
        value = conn.execute(query, params).fetchone()[0]
    return int(value or 0)


def clean_title(script: str) -> str:
    first = re.sub(r"\s+", " ", script.strip()).strip()
    return first[:24] or "Untitled project"


def split_script(script: str) -> list[str]:
    pieces = re.split(r"(?<=[。！？.!?])\s*|\n+", script)
    cleaned = [piece.strip() for piece in pieces if piece and piece.strip()]
    if len(cleaned) <= 1:
        cleaned = [script.strip()[i : i + 90] for i in range(0, len(script.strip()), 90)]
    return cleaned[:12]


def guess_entities(script: str) -> list[dict[str, str]]:
    patterns = [
        ("character", ["小明", "小红", "少年", "女孩", "男孩", "老师", "主角", "老人", "女孩"]),
        ("object", ["钥匙", "手机", "盒子", "书", "信", "机器", "产品", "背包", "手表"]),
        ("scene", ["城市", "房间", "办公室", "学校", "街道", "森林", "海边", "实验室", "广场"]),
    ]
    found: list[dict[str, str]] = []
    for entity_type, words in patterns:
        for word in words:
            if word in script and not any(item["name"] == word for item in found):
                found.append(
                    {
                        "name": word,
                        "type": entity_type,
                        "description": f"剧本中出现的{word}，需要在分帧画面中保持视觉一致。",
                    }
                )
    if not found:
        found = [
            {"name": "主角", "type": "character", "description": "故事核心人物，承担主要行动。"},
            {"name": "关键物品", "type": "object", "description": "推动剧情发展的重要道具。"},
            {"name": "主要场景", "type": "scene", "description": "故事发生的主要环境。"},
        ]
    if not any(item["type"] == "concept" for item in found):
        found.append({"name": "核心情绪", "type": "concept", "description": "贯穿剧本的画面氛围和情绪主题。"})
    return found[:10]


def default_prompt(entity: dict[str, Any]) -> str:
    type_label = {
        "character": "consistent character design",
        "object": "clean product prop design",
        "scene": "cinematic environment concept art",
        "concept": "visual mood board symbol",
    }.get(entity["type"], "visual reference")
    return f"{type_label}, {entity['name']}, {entity['description']}, high detail, neutral background"


def create_project_graph(project_id: str, script: str) -> None:
    now = now_iso()
    entities = guess_entities(script)
    with connect() as conn:
        conn.execute("DELETE FROM graph_edges WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM graph_nodes WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM entities WHERE project_id = ?", (project_id,))
        entity_records: list[dict[str, Any]] = []
        for index, item in enumerate(entities):
            entity_id = str(uuid.uuid4())
            prompt = default_prompt(item)
            entity_records.append({**item, "id": entity_id, "prompt": prompt})
            conn.execute(
                """
                INSERT INTO entities (
                    id, project_id, name, type, description, visual_description, prompt,
                    status, occurrence_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_id,
                    project_id,
                    item["name"],
                    item["type"],
                    item["description"],
                    item["description"],
                    prompt,
                    "image_pending",
                    max(1, script.count(item["name"])),
                    now,
                    now,
                ),
            )
            angle = index * 360 / max(1, len(entities))
            conn.execute(
                """
                INSERT INTO graph_nodes (
                    id, project_id, type, name, description, source_text, entity_id, x, y
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    project_id,
                    item["type"],
                    item["name"],
                    item["description"],
                    item["name"],
                    entity_id,
                    340 + 220 * (index % 3),
                    160 + 130 * (index // 3),
                ),
            )
        nodes = conn.execute("SELECT * FROM graph_nodes WHERE project_id = ?", (project_id,)).fetchall()
        for index in range(max(0, len(nodes) - 1)):
            conn.execute(
                """
                INSERT INTO graph_edges (
                    id, project_id, source_node_id, target_node_id, relation, description, source_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    project_id,
                    nodes[index]["id"],
                    nodes[index + 1]["id"],
                    "关联",
                    f"{nodes[index]['name']} 与 {nodes[index + 1]['name']} 在剧本中存在叙事关联。",
                    script[:160],
                ),
            )
        conn.execute(
            "UPDATE projects SET status = ?, progress = ?, updated_at = ? WHERE id = ?",
            ("graph_ready", 45, now, project_id),
        )


def entity_with_images(entity_id: str) -> dict[str, Any]:
    with connect() as conn:
        entity = row_to_dict(conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone())
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        images = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM entity_images WHERE entity_id = ? ORDER BY created_at DESC", (entity_id,)
            ).fetchall()
        ]
    entity["images"] = images
    return entity


def create_svg_image(entity: dict[str, Any], prompt: str, image_id: str) -> Path:
    project_id = entity["project_id"]
    target_dir = GENERATED_DIR / project_id / entity["id"]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{image_id}.svg"
    colors = {
        "character": ("#2563eb", "#dbeafe"),
        "object": ("#16a34a", "#dcfce7"),
        "scene": ("#9333ea", "#f3e8ff"),
        "concept": ("#ea580c", "#ffedd5"),
    }
    primary, bg = colors.get(entity["type"], ("#475569", "#f8fafc"))
    safe_name = entity["name"].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    safe_prompt = prompt[:120].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="960" height="640" viewBox="0 0 960 640">
  <rect width="960" height="640" fill="{bg}"/>
  <circle cx="480" cy="248" r="136" fill="{primary}" opacity="0.16"/>
  <rect x="226" y="138" width="508" height="318" rx="36" fill="white" stroke="{primary}" stroke-width="6"/>
  <text x="480" y="286" text-anchor="middle" font-family="Arial, sans-serif" font-size="54" font-weight="700" fill="{primary}">{safe_name}</text>
  <text x="480" y="350" text-anchor="middle" font-family="Arial, sans-serif" font-size="24" fill="#334155">{entity["type"]} reference image</text>
  <text x="480" y="410" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" fill="#64748b">{safe_prompt}</text>
</svg>"""
    target.write_text(svg, encoding="utf-8")
    return target


def storage_url(path: Path) -> str:
    relative = path.resolve().relative_to(DATA_DIR)
    return "/storage/" + relative.as_posix()


def get_graph(project_id: str) -> dict[str, Any]:
    nodes = list_rows("SELECT * FROM graph_nodes WHERE project_id = ? ORDER BY rowid", (project_id,))
    edges = list_rows("SELECT * FROM graph_edges WHERE project_id = ? ORDER BY rowid", (project_id,))
    return {"nodes": nodes, "edges": edges}


def get_entities(project_id: str) -> list[dict[str, Any]]:
    entities = list_rows("SELECT * FROM entities WHERE project_id = ? ORDER BY type, name", (project_id,))
    for entity in entities:
        entity["images"] = list_rows(
            "SELECT * FROM entity_images WHERE entity_id = ? ORDER BY created_at DESC", (entity["id"],)
        )
    return entities


def build_frame_prompt(description: str, entity_names: list[str], refs: list[str]) -> str:
    names = ", ".join(entity_names) if entity_names else "no fixed entity"
    references = ", ".join(refs) if refs else "no reference image"
    return f"{description}\nReferenced entities: {names}\nReference images: {references}"


def generate_frames(project_id: str) -> list[dict[str, Any]]:
    project = get_project(project_id)
    entities = get_entities(project_id)
    chunks = split_script(project["script"])
    now = now_iso()
    with connect() as conn:
        conn.execute("DELETE FROM frames WHERE project_id = ?", (project_id,))
        for index, source in enumerate(chunks, start=1):
            related = [entity for entity in entities if entity["name"] in source] or entities[: min(3, len(entities))]
            entity_ids = [entity["id"] for entity in related]
            image_ids: list[str] = []
            image_urls: list[str] = []
            names: list[str] = []
            for entity in related:
                names.append(entity["name"])
                if entity.get("main_image_id"):
                    image_ids.append(entity["main_image_id"])
                    image = conn.execute(
                        "SELECT image_url FROM entity_images WHERE id = ?", (entity["main_image_id"],)
                    ).fetchone()
                    if image:
                        image_urls.append(image["image_url"])
            description = f"第 {index} 帧：{source}。画面需要突出 {', '.join(names) if names else '核心情绪'}。"
            prompt = build_frame_prompt(description, names, image_urls)
            conn.execute(
                """
                INSERT INTO frames (
                    id, project_id, frame_index, source_text, description, camera, mood,
                    entity_ids, reference_image_ids, prompt, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    project_id,
                    index,
                    source,
                    description,
                    "中景，稳定镜头",
                    "cinematic, coherent, story-driven",
                    json.dumps(entity_ids, ensure_ascii=False),
                    json.dumps(image_ids, ensure_ascii=False),
                    prompt,
                    now,
                    now,
                ),
            )
        conn.execute(
            "UPDATE projects SET status = ?, progress = ?, updated_at = ? WHERE id = ?",
            ("frames_ready", 85, now, project_id),
        )
    return get_frames(project_id)


def get_frames(project_id: str) -> list[dict[str, Any]]:
    frames = list_rows("SELECT * FROM frames WHERE project_id = ? ORDER BY frame_index", (project_id,))
    entities = {entity["id"]: entity for entity in get_entities(project_id)}
    for frame in frames:
        frame["entity_ids"] = json.loads(frame["entity_ids"])
        frame["reference_image_ids"] = json.loads(frame["reference_image_ids"])
        frame["entities"] = [entities[eid] for eid in frame["entity_ids"] if eid in entities]
    return frames


app = FastAPI(title=settings.app_name)

origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict[str, str]:
    ensure_directories()
    with connect() as conn:
        conn.execute("SELECT 1").fetchone()
    return {"status": "ok", "database": "ok", "storage": "ok"}


@app.post("/api/projects")
def create_project(payload: ProjectCreate) -> dict[str, Any]:
    project_id = str(uuid.uuid4())
    title = payload.title or clean_title(payload.script)
    now = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, title, script, content_type, status, progress, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, title, payload.script, payload.content_type, "draft", 10, now, now),
        )
    return get_project(project_id)


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    rows = list_rows("SELECT * FROM projects ORDER BY updated_at DESC")
    return [get_project(row["id"]) for row in rows]


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str) -> dict[str, Any]:
    project = get_project(project_id)
    project["graph"] = get_graph(project_id)
    project["entities"] = get_entities(project_id)
    project["frames"] = get_frames(project_id)
    project["exports"] = list_rows("SELECT * FROM exports WHERE project_id = ? ORDER BY created_at DESC", (project_id,))
    return project


@app.post("/api/projects/{project_id}/analyze")
def analyze_project(project_id: str) -> dict[str, Any]:
    project = get_project(project_id)
    with connect() as conn:
        conn.execute(
            "UPDATE projects SET status = ?, progress = ?, updated_at = ? WHERE id = ?",
            ("analyzing", 25, now_iso(), project_id),
        )
    create_project_graph(project_id, project["script"])
    return project_detail(project_id)


@app.get("/api/projects/{project_id}/graph")
def graph(project_id: str) -> dict[str, Any]:
    get_project(project_id)
    return get_graph(project_id)


@app.get("/api/projects/{project_id}/entities")
def entities(project_id: str) -> list[dict[str, Any]]:
    get_project(project_id)
    return get_entities(project_id)


@app.patch("/api/entities/{entity_id}")
def update_entity(entity_id: str, payload: EntityUpdate) -> dict[str, Any]:
    entity = entity_with_images(entity_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return entity
    allowed = {
        "name",
        "type",
        "description",
        "visual_description",
        "prompt",
        "status",
        "main_image_id",
    }
    assignments = [f"{key} = ?" for key in updates if key in allowed]
    values = [updates[key] for key in updates if key in allowed]
    if not assignments:
        return entity
    assignments.append("updated_at = ?")
    values.append(now_iso())
    values.append(entity_id)
    with connect() as conn:
        conn.execute(f"UPDATE entities SET {', '.join(assignments)} WHERE id = ?", tuple(values))
    return entity_with_images(entity_id)


@app.post("/api/entities/{entity_id}/images")
def generate_entity_image(entity_id: str, payload: EntityImageCreate) -> dict[str, Any]:
    entity = entity_with_images(entity_id)
    prompt = payload.prompt or entity.get("prompt") or default_prompt(entity)
    image_id = str(uuid.uuid4())
    path = create_svg_image(entity, prompt, image_id)
    image_url = storage_url(path)
    now = now_iso()
    with connect() as conn:
        existing_count = conn.execute(
            "SELECT COUNT(*) FROM entity_images WHERE entity_id = ?", (entity_id,)
        ).fetchone()[0]
        is_main = 1 if existing_count == 0 else 0
        conn.execute(
            """
            INSERT INTO entity_images (
                id, entity_id, project_id, image_url, file_path, prompt, is_main, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (image_id, entity_id, entity["project_id"], image_url, str(path), prompt, is_main, now),
        )
        if is_main:
            conn.execute(
                "UPDATE entities SET main_image_id = ?, status = ?, updated_at = ? WHERE id = ?",
                (image_id, "image_ready", now, entity_id),
            )
    return entity_with_images(entity_id)


@app.post("/api/entities/{entity_id}/reference-images")
async def upload_reference_image(entity_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    entity = entity_with_images(entity_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        raise HTTPException(status_code=400, detail="Unsupported image type")
    image_id = str(uuid.uuid4())
    target_dir = UPLOAD_DIR / entity["project_id"] / entity_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{image_id}{suffix}"
    with target.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    image_url = storage_url(target)
    prompt = entity.get("prompt") or default_prompt(entity)
    now = now_iso()
    with connect() as conn:
        existing_count = conn.execute(
            "SELECT COUNT(*) FROM entity_images WHERE entity_id = ?", (entity_id,)
        ).fetchone()[0]
        is_main = 1 if existing_count == 0 else 0
        conn.execute(
            """
            INSERT INTO entity_images (
                id, entity_id, project_id, image_url, file_path, prompt, reference_image_url, is_main, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (image_id, entity_id, entity["project_id"], image_url, str(target), prompt, image_url, is_main, now),
        )
        if is_main:
            conn.execute(
                "UPDATE entities SET main_image_id = ?, status = ?, updated_at = ? WHERE id = ?",
                (image_id, "image_ready", now, entity_id),
            )
    return entity_with_images(entity_id)


@app.post("/api/projects/{project_id}/frames/generate")
def create_frames(project_id: str) -> list[dict[str, Any]]:
    get_project(project_id)
    return generate_frames(project_id)


@app.get("/api/projects/{project_id}/frames")
def frames(project_id: str) -> list[dict[str, Any]]:
    get_project(project_id)
    return get_frames(project_id)


@app.patch("/api/frames/{frame_id}")
def update_frame(frame_id: str, payload: FrameUpdate) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM frames WHERE id = ?", (frame_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Frame not found")
        frame = dict(row)
        updates = payload.model_dump(exclude_unset=True)
        if "entity_ids" in updates and updates["entity_ids"] is not None:
            updates["entity_ids"] = json.dumps(updates["entity_ids"], ensure_ascii=False)
            updates["reference_image_ids"] = json.dumps([], ensure_ascii=False)
        assignments = [f"{key} = ?" for key in updates if key in {"description", "camera", "mood", "entity_ids", "reference_image_ids"}]
        values = [updates[key] for key in updates if key in {"description", "camera", "mood", "entity_ids", "reference_image_ids"}]
        assignments.append("updated_at = ?")
        values.append(now_iso())
        values.append(frame_id)
        conn.execute(f"UPDATE frames SET {', '.join(assignments)} WHERE id = ?", tuple(values))
    return next(item for item in get_frames(frame["project_id"]) if item["id"] == frame_id)


@app.post("/api/projects/{project_id}/export")
def export_project(project_id: str) -> dict[str, Any]:
    project = project_detail(project_id)
    export_id = str(uuid.uuid4())
    target_dir = EXPORT_DIR / project_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{export_id}.zip"
    manifest = {
        "project": project,
        "graph": project["graph"],
        "entities": project["entities"],
        "frames": project["frames"],
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("script.txt", project["script"])
        frame_md = "\n\n".join([f"## Frame {frame['frame_index']}\n{frame['prompt']}" for frame in project["frames"]])
        archive.writestr("frames.md", frame_md)
        for entity in project["entities"]:
            for image in entity["images"]:
                file_path = Path(image["file_path"])
                if file_path.exists():
                    archive.write(file_path, f"images/{entity['name']}/{file_path.name}")
    file_url = storage_url(target)
    now = now_iso()
    with connect() as conn:
        conn.execute(
            "INSERT INTO exports (id, project_id, file_url, file_path, created_at) VALUES (?, ?, ?, ?, ?)",
            (export_id, project_id, file_url, str(target), now),
        )
        conn.execute(
            "UPDATE projects SET status = ?, progress = ?, updated_at = ? WHERE id = ?",
            ("export_ready", 100, now, project_id),
        )
    return {"id": export_id, "file_url": file_url, "created_at": now}


ensure_directories()
app.mount("/storage/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/storage/generated", StaticFiles(directory=GENERATED_DIR), name="generated")
app.mount("/storage/exports", StaticFiles(directory=EXPORT_DIR), name="exports")

if FRONTEND_DIST_DIR.exists():
    assets_dir = FRONTEND_DIST_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str) -> FileResponse:
        requested = FRONTEND_DIST_DIR / full_path
        if full_path and requested.exists() and requested.is_file():
            return FileResponse(requested)
        return FileResponse(FRONTEND_DIST_DIR / "index.html")
