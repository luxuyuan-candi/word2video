from __future__ import annotations

import json
import re
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings

from app.script_parser import ParsedEntity, ParsedEvent, ParsedRelation, parse_project_scripts


BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

FrameScope = Literal["selected_scripts"]


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
    return resolve_path(settings.database_url.removeprefix(prefix))


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


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    ensure_directories()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                script TEXT NOT NULL DEFAULT '',
                content_type TEXT,
                active_script_id TEXT,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_scripts (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                content_type TEXT,
                order_index INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'draft',
                word_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS graph_nodes (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                source_text TEXT,
                source_script_ids TEXT NOT NULL DEFAULT '[]',
                change_state TEXT NOT NULL DEFAULT 'existing',
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
                source_script_ids TEXT NOT NULL DEFAULT '[]',
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
                source_script_ids TEXT NOT NULL DEFAULT '[]',
                merge_candidate_ids TEXT NOT NULL DEFAULT '[]',
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
                script_id TEXT,
                script_title TEXT,
                scope TEXT NOT NULL DEFAULT 'current_script',
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
                script_id TEXT,
                scope TEXT NOT NULL DEFAULT 'current_script',
                file_url TEXT NOT NULL,
                file_path TEXT NOT NULL,
                frame_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            """
        )
        for table, columns in {
            "projects": [("active_script_id", "TEXT")],
            "graph_nodes": [("source_script_ids", "TEXT NOT NULL DEFAULT '[]'"), ("change_state", "TEXT NOT NULL DEFAULT 'existing'")],
            "graph_edges": [("source_script_ids", "TEXT NOT NULL DEFAULT '[]'")],
            "entities": [("source_script_ids", "TEXT NOT NULL DEFAULT '[]'"), ("merge_candidate_ids", "TEXT NOT NULL DEFAULT '[]'")],
            "frames": [("script_id", "TEXT"), ("script_title", "TEXT"), ("scope", "TEXT NOT NULL DEFAULT 'current_script'")],
            "exports": [("script_id", "TEXT"), ("scope", "TEXT NOT NULL DEFAULT 'current_script'"), ("frame_count", "INTEGER NOT NULL DEFAULT 0")],
        }.items():
            for column, definition in columns:
                add_column_if_missing(conn, table, column, definition)
        backfill_scripts(conn)


def backfill_scripts(conn: sqlite3.Connection) -> None:
    now = now_iso()
    projects = conn.execute("SELECT * FROM projects").fetchall()
    for project in projects:
        count = conn.execute("SELECT COUNT(*) FROM project_scripts WHERE project_id = ?", (project["id"],)).fetchone()[0]
        if count:
            continue
        script = project["script"] or ""
        if not script:
            continue
        script_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO project_scripts (
                id, project_id, title, content, content_type, order_index, status,
                word_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                script_id,
                project["id"],
                clean_title(script),
                script,
                project["content_type"],
                1,
                "draft",
                len(script),
                project["created_at"] or now,
                now,
            ),
        )
        conn.execute("UPDATE projects SET active_script_id = ? WHERE id = ?", (script_id, project["id"]))


class ProjectCreate(BaseModel):
    title: str | None = None
    script_title: str | None = None
    script: str | None = None
    content_type: str | None = None


class ProjectUpdate(BaseModel):
    title: str


class ScriptCreate(BaseModel):
    title: str | None = None
    content: str = ""
    content_type: str | None = None


class ScriptUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    content_type: str | None = None


class ActiveScriptUpdate(BaseModel):
    script_id: str


class EntityUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    description: str | None = None
    visual_description: str | None = None
    prompt: str | None = None
    status: str | None = None
    main_image_id: str | None = None


class EntityMerge(BaseModel):
    target_entity_id: str


class EntityImageCreate(BaseModel):
    prompt: str | None = None


class FrameGenerate(BaseModel):
    scope: FrameScope = "selected_scripts"
    script_ids: list[str] = Field(default_factory=list)


class FrameUpdate(BaseModel):
    description: str | None = None
    camera: str | None = None
    mood: str | None = None
    entity_ids: list[str] | None = None


class ExportCreate(BaseModel):
    scope: FrameScope = "selected_scripts"
    script_ids: list[str] = Field(default_factory=list)


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def list_rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    with connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def scalar(query: str, params: tuple[Any, ...] = ()) -> int:
    with connect() as conn:
        value = conn.execute(query, params).fetchone()[0]
    return int(value or 0)


def json_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def dump_ids(values: list[str]) -> str:
    return json.dumps(sorted(set(values)), ensure_ascii=False)


def clean_title(script: str) -> str:
    first = re.sub(r"\s+", " ", script.strip()).strip()
    return first[:24] or "未命名剧本"


def split_script(script: str) -> list[str]:
    pieces = re.split(r"(?<=[。！？.!?])\s*|\n+", script)
    cleaned = [piece.strip() for piece in pieces if piece and piece.strip()]
    if len(cleaned) <= 1:
        cleaned = [script.strip()[i : i + 90] for i in range(0, len(script.strip()), 90)]
    return cleaned[:24]


def storage_url(path: Path) -> str:
    relative = path.resolve().relative_to(DATA_DIR)
    return "/storage/" + relative.as_posix()


def get_script(script_id: str) -> dict[str, Any]:
    with connect() as conn:
        script = row_to_dict(conn.execute("SELECT * FROM project_scripts WHERE id = ?", (script_id,)).fetchone())
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    return script


def get_project(project_id: str) -> dict[str, Any]:
    with connect() as conn:
        project = row_to_dict(conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["script_count"] = scalar("SELECT COUNT(*) FROM project_scripts WHERE project_id = ?", (project_id,))
    project["entity_count"] = scalar("SELECT COUNT(*) FROM entities WHERE project_id = ?", (project_id,))
    project["completed_entity_image_count"] = scalar(
        "SELECT COUNT(*) FROM entities WHERE project_id = ? AND main_image_id IS NOT NULL",
        (project_id,),
    )
    project["frame_count"] = scalar("SELECT COUNT(*) FROM frames WHERE project_id = ?", (project_id,))
    return project


def get_scripts(project_id: str) -> list[dict[str, Any]]:
    return list_rows("SELECT * FROM project_scripts WHERE project_id = ? ORDER BY order_index, created_at", (project_id,))


def choose_script(project: dict[str, Any], script_id: str | None = None) -> dict[str, Any]:
    selected_id = script_id or project.get("active_script_id")
    if not selected_id:
        scripts = get_scripts(project["id"])
        if not scripts:
            raise HTTPException(status_code=400, detail="Project has no script")
        return scripts[0]
    script = get_script(selected_id)
    if script["project_id"] != project["id"]:
        raise HTTPException(status_code=400, detail="Script does not belong to project")
    return script


def get_scripts_by_ids(project_id: str, script_ids: list[str]) -> list[dict[str, Any]]:
    scripts = get_scripts(project_id)
    if not script_ids:
        return scripts
    selected = [script for script in scripts if script["id"] in set(script_ids)]
    if len(selected) != len(set(script_ids)):
        raise HTTPException(status_code=400, detail="Some scripts do not belong to project")
    return selected


def entity_patterns() -> list[tuple[str, list[str]]]:
    return [
        ("character", ["小明", "小红", "少年", "女孩", "男孩", "老师", "主角", "老人", "摄影师", "母亲", "父亲", "队长", "医生", "学生", "机器人"]),
        ("object", ["钥匙", "手机", "盒子", "书", "信", "机器", "产品", "背包", "手表", "相机", "门", "电脑", "地图", "灯", "飞船", "药瓶"]),
        ("scene", ["城市", "房间", "办公室", "学校", "街道", "森林", "海边", "实验室", "广场", "天台", "书店", "走廊", "教室", "车站", "医院", "餐厅"]),
        ("concept", ["星河", "梦想", "危险", "秘密", "回忆", "希望", "恐惧", "温暖", "孤独", "未来", "危机", "胜利"]),
    ]


def guess_entities(script: str) -> list[dict[str, str]]:
    patterns = entity_patterns()
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
    return found[:18]


def split_sentences(content: str) -> list[str]:
    sentences = re.split(r"(?<=[。！？.!?])\s*|\n+", content)
    return [sentence.strip() for sentence in sentences if sentence and sentence.strip()]


def summarize_event(sentence: str, index: int) -> str:
    compact = re.sub(r"\s+", "", sentence)
    return compact[:16] or f"事件{index}"


def event_description(sentence: str, script_title: str) -> str:
    return f"《{script_title}》中的叙事事件：{sentence}"


def default_prompt(entity: dict[str, Any]) -> str:
    type_label = {
        "character": "consistent character design",
        "object": "clean product prop design",
        "scene": "cinematic environment concept art",
        "concept": "visual mood board symbol",
    }.get(entity["type"], "visual reference")
    return f"{type_label}, {entity['name']}, {entity['description']}, high detail, neutral background"


def upsert_entity(conn: sqlite3.Connection, project_id: str, script_id: str, item: dict[str, str], script: str) -> str:
    now = now_iso()
    existing = conn.execute(
        "SELECT * FROM entities WHERE project_id = ? AND lower(name) = lower(?)",
        (project_id, item["name"]),
    ).fetchone()
    if existing:
        ids = json_list(existing["source_script_ids"])
        ids.append(script_id)
        occurrence_count = int(existing["occurrence_count"] or 0) + max(1, script.count(item["name"]))
        conn.execute(
            """
            UPDATE entities
            SET source_script_ids = ?, occurrence_count = ?, updated_at = ?
            WHERE id = ?
            """,
            (dump_ids(ids), occurrence_count, now, existing["id"]),
        )
        return existing["id"]

    entity_id = str(uuid.uuid4())
    prompt = default_prompt(item)
    conn.execute(
        """
        INSERT INTO entities (
            id, project_id, name, type, description, visual_description, prompt,
            status, source_script_ids, occurrence_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            dump_ids([script_id]),
            max(1, script.count(item["name"])),
            now,
            now,
        ),
    )
    return entity_id


def upsert_graph_node(
    conn: sqlite3.Connection,
    project_id: str,
    script_id: str,
    item: dict[str, str],
    entity_id: str,
    index: int,
) -> str:
    existing = conn.execute(
        "SELECT * FROM graph_nodes WHERE project_id = ? AND entity_id = ?",
        (project_id, entity_id),
    ).fetchone()
    if existing:
        ids = json_list(existing["source_script_ids"])
        ids.append(script_id)
        conn.execute(
            "UPDATE graph_nodes SET source_script_ids = ?, change_state = ? WHERE id = ?",
            (dump_ids(ids), "updated", existing["id"]),
        )
        return existing["id"]
    node_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO graph_nodes (
            id, project_id, type, name, description, source_text, source_script_ids,
            change_state, entity_id, x, y
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id,
            project_id,
            item["type"],
            item["name"],
            item["description"],
            item["name"],
            dump_ids([script_id]),
            "new",
            entity_id,
            160 + 180 * (index % 4),
            140 + 125 * (index // 4),
        ),
    )
    return node_id


def insert_event_node(
    conn: sqlite3.Connection,
    project_id: str,
    script_id: str,
    script_title: str,
    sentence: str,
    index: int,
) -> str:
    node_id = str(uuid.uuid4())
    event_name = summarize_event(sentence, index)
    conn.execute(
        """
        INSERT INTO graph_nodes (
            id, project_id, type, name, description, source_text, source_script_ids,
            change_state, entity_id, x, y
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id,
            project_id,
            "event",
            event_name,
            event_description(sentence, script_title),
            sentence,
            dump_ids([script_id]),
            "new",
            None,
            180 + 150 * (index % 5),
            320 + 105 * (index // 5),
        ),
    )
    return node_id


def insert_graph_edge(
    conn: sqlite3.Connection,
    project_id: str,
    source_node_id: str,
    target_node_id: str,
    relation: str,
    description: str,
    source_text: str,
    script_id: str,
) -> None:
    exists = conn.execute(
        """
        SELECT id FROM graph_edges
        WHERE project_id = ? AND source_node_id = ? AND target_node_id = ? AND relation = ?
        """,
        (project_id, source_node_id, target_node_id, relation),
    ).fetchone()
    if exists:
        return
    conn.execute(
        """
        INSERT INTO graph_edges (
            id, project_id, source_node_id, target_node_id, relation,
            description, source_text, source_script_ids
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid.uuid4()),
            project_id,
            source_node_id,
            target_node_id,
            relation,
            description,
            source_text,
            dump_ids([script_id]),
        ),
    )


def upsert_parsed_entity(conn: sqlite3.Connection, project_id: str, parsed: ParsedEntity) -> str:
    now = now_iso()
    script_ids = [script_id for script_id, _ in parsed.mentions]
    occurrence_count = max(1, len(parsed.mentions))
    existing = conn.execute(
        "SELECT * FROM entities WHERE project_id = ? AND lower(name) = lower(?)",
        (project_id, parsed.name),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE entities
            SET type = ?, description = ?, visual_description = COALESCE(visual_description, ?),
                prompt = COALESCE(prompt, ?), source_script_ids = ?, occurrence_count = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                parsed.type,
                parsed.description,
                parsed.description,
                default_prompt({"type": parsed.type, "name": parsed.name, "description": parsed.description}),
                dump_ids(script_ids),
                occurrence_count,
                now,
                existing["id"],
            ),
        )
        return existing["id"]

    entity_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO entities (
            id, project_id, name, type, description, visual_description, prompt,
            status, source_script_ids, occurrence_count, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_id,
            project_id,
            parsed.name,
            parsed.type,
            parsed.description,
            parsed.description,
            default_prompt({"type": parsed.type, "name": parsed.name, "description": parsed.description}),
            "image_pending",
            dump_ids(script_ids),
            occurrence_count,
            now,
            now,
        ),
    )
    return entity_id


def insert_parsed_entity_node(
    conn: sqlite3.Connection,
    project_id: str,
    parsed: ParsedEntity,
    entity_id: str,
    index: int,
) -> str:
    script_ids = [script_id for script_id, _ in parsed.mentions]
    source_text = " / ".join([text for _, text in parsed.mentions[:3]]) or parsed.name
    node_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO graph_nodes (
            id, project_id, type, name, description, source_text, source_script_ids,
            change_state, entity_id, x, y
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id,
            project_id,
            parsed.type,
            parsed.name,
            parsed.description,
            source_text,
            dump_ids(script_ids),
            "updated" if script_ids else "existing",
            entity_id,
            120 + 160 * index,
            140,
        ),
    )
    return node_id


def insert_parsed_event_node(conn: sqlite3.Connection, project_id: str, event: ParsedEvent) -> str:
    node_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO graph_nodes (
            id, project_id, type, name, description, source_text, source_script_ids,
            change_state, entity_id, x, y
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            node_id,
            project_id,
            "event",
            event.name,
            event.description,
            event.source_text,
            dump_ids([event.script_id]),
            "new",
            None,
            120 + 130 * ((event.order - 1) % 6),
            420 + 95 * ((event.order - 1) // 6),
        ),
    )
    return node_id


def insert_parsed_relation(
    conn: sqlite3.Connection,
    project_id: str,
    relation: ParsedRelation,
    key_to_node: dict[str, str],
) -> None:
    source_node_id = key_to_node.get(relation.source_key)
    target_node_id = key_to_node.get(relation.target_key)
    if not source_node_id or not target_node_id or source_node_id == target_node_id:
        return
    insert_graph_edge(
        conn,
        project_id,
        source_node_id,
        target_node_id,
        relation.relation,
        relation.description,
        relation.source_text,
        relation.script_id,
    )


def relayout_graph(conn: sqlite3.Connection, project_id: str) -> None:
    rows = conn.execute("SELECT id, type FROM graph_nodes WHERE project_id = ? ORDER BY rowid", (project_id,)).fetchall()
    y_by_type = {"character": 110, "object": 230, "scene": 350, "event": 500, "concept": 680}
    counts: dict[str, int] = {}
    for row in rows:
        node_type = row["type"]
        count = counts.get(node_type, 0)
        counts[node_type] = count + 1
        conn.execute(
            "UPDATE graph_nodes SET x = ?, y = ? WHERE id = ?",
            (120 + 150 * count, y_by_type.get(node_type, 760), row["id"]),
        )


def analyze_project_graph(project_id: str) -> dict[str, Any]:
    scripts = get_scripts(project_id)
    if not scripts:
        raise HTTPException(status_code=400, detail="Project has no script")
    parsed = parse_project_scripts(scripts)
    now = now_iso()
    with connect() as conn:
        conn.execute("DELETE FROM graph_edges WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM graph_nodes WHERE project_id = ?", (project_id,))
        for script in scripts:
            conn.execute("UPDATE project_scripts SET status = ?, updated_at = ? WHERE id = ?", ("analyzing", now, script["id"]))

        key_to_node: dict[str, str] = {}
        for index, entity in enumerate(parsed.entities):
            entity_id = upsert_parsed_entity(conn, project_id, entity)
            key_to_node[f"entity:{entity.name}"] = insert_parsed_entity_node(conn, project_id, entity, entity_id, index)
        for event in parsed.events:
            key_to_node[event.key] = insert_parsed_event_node(conn, project_id, event)
        for relation in parsed.relations:
            insert_parsed_relation(conn, project_id, relation, key_to_node)
        relayout_graph(conn, project_id)

        for script in scripts:
            conn.execute("UPDATE project_scripts SET status = ?, updated_at = ? WHERE id = ?", ("analyzed", now, script["id"]))
        conn.execute(
            "UPDATE projects SET status = ?, progress = ?, updated_at = ? WHERE id = ?",
            ("graph_ready", 45, now, project_id),
        )
    return project_detail(project_id)


def analyze_script_into_project(project_id: str, script_id: str) -> dict[str, Any]:
    project = get_project(project_id)
    script = get_script(script_id)
    if script["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Script does not belong to project")
    now = now_iso()
    entities = guess_entities(script["content"])
    with connect() as conn:
        conn.execute("UPDATE project_scripts SET status = ?, updated_at = ? WHERE id = ?", ("analyzing", now, script_id))
        entity_node_ids: dict[str, str] = {}
        for index, item in enumerate(entities):
            entity_id = upsert_entity(conn, project_id, script_id, item, script["content"])
            entity_node_ids[item["name"]] = upsert_graph_node(conn, project_id, script_id, item, entity_id, index)

        previous_event_id: str | None = None
        sentences = split_sentences(script["content"])
        for sentence_index, sentence in enumerate(sentences, start=1):
            event_id = insert_event_node(conn, project_id, script_id, script["title"], sentence, sentence_index)
            if previous_event_id:
                insert_graph_edge(
                    conn,
                    project_id,
                    previous_event_id,
                    event_id,
                    "然后",
                    "两个事件在剧幕中按顺序连续发生。",
                    sentence,
                    script_id,
                )
            previous_event_id = event_id

            matched_entities = [item for item in entities if item["name"] in sentence]
            if not matched_entities:
                matched_entities = [item for item in entities[:2] if item["type"] in {"character", "scene"}]
            for item in matched_entities:
                node_id = entity_node_ids.get(item["name"])
                if not node_id:
                    continue
                relation = {
                    "character": "参与",
                    "scene": "发生于",
                    "object": "关联道具",
                    "concept": "表达",
                }.get(item["type"], "关联")
                insert_graph_edge(
                    conn,
                    project_id,
                    node_id,
                    event_id,
                    relation,
                    f"{item['name']} 与该叙事事件存在“{relation}”关系。",
                    sentence,
                    script_id,
                )

        entity_items = list(entities)
        for left_index, left in enumerate(entity_items):
            for right in entity_items[left_index + 1 :]:
                if left["type"] == right["type"]:
                    continue
                if left["name"] not in script["content"] or right["name"] not in script["content"]:
                    continue
                left_node = entity_node_ids.get(left["name"])
                right_node = entity_node_ids.get(right["name"])
                if left_node and right_node:
                    insert_graph_edge(
                        conn,
                        project_id,
                        left_node,
                        right_node,
                        "共现",
                        "两个实体在同一剧幕中共同出现。",
                        script["content"][:180],
                        script_id,
                    )

        nodes = conn.execute("SELECT id, type FROM graph_nodes WHERE project_id = ? ORDER BY rowid", (project_id,)).fetchall()
        type_offsets = {"character": 110, "object": 230, "scene": 350, "event": 470, "concept": 590}
        type_counts: dict[str, int] = {}
        for node in nodes:
            node_type = node["type"]
            count = type_counts.get(node_type, 0)
            type_counts[node_type] = count + 1
            conn.execute(
                "UPDATE graph_nodes SET x = ?, y = ? WHERE id = ?",
                (120 + 165 * count, type_offsets.get(node_type, 640), node["id"]),
            )
        conn.execute("UPDATE project_scripts SET status = ?, updated_at = ? WHERE id = ?", ("analyzed", now, script_id))
        conn.execute(
            "UPDATE projects SET active_script_id = ?, status = ?, progress = ?, updated_at = ? WHERE id = ?",
            (script_id, "graph_ready", 45, now, project_id),
        )
    return project_detail(project_id)


def entity_with_images(entity_id: str) -> dict[str, Any]:
    with connect() as conn:
        entity = row_to_dict(conn.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone())
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        images = [dict(row) for row in conn.execute("SELECT * FROM entity_images WHERE entity_id = ? ORDER BY created_at DESC", (entity_id,))]
    return normalize_entity({**entity, "images": images})


def normalize_entity(entity: dict[str, Any]) -> dict[str, Any]:
    entity["source_script_ids"] = json_list(entity.get("source_script_ids"))
    entity["source_script_count"] = len(entity["source_script_ids"])
    entity["merge_candidate_ids"] = json_list(entity.get("merge_candidate_ids"))
    entity.setdefault("images", [])
    return entity


def create_svg_image(entity: dict[str, Any], prompt: str, image_id: str) -> Path:
    target_dir = GENERATED_DIR / entity["project_id"] / entity["id"]
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{image_id}.svg"
    colors = {
        "character": ("#2563eb", "#dbeafe"),
        "object": ("#16a34a", "#dcfce7"),
        "scene": ("#9333ea", "#f3e8ff"),
        "concept": ("#ea580c", "#ffedd5"),
    }
    primary, bg = colors.get(entity["type"], ("#475569", "#f8fafc"))
    safe_name = escape_xml(entity["name"])
    safe_prompt = escape_xml(prompt[:120])
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


def escape_xml(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def get_graph(project_id: str) -> dict[str, Any]:
    nodes = list_rows("SELECT * FROM graph_nodes WHERE project_id = ? ORDER BY rowid", (project_id,))
    edges = list_rows("SELECT * FROM graph_edges WHERE project_id = ? ORDER BY rowid", (project_id,))
    for node in nodes:
        node["source_script_ids"] = json_list(node.get("source_script_ids"))
    for edge in edges:
        edge["source_script_ids"] = json_list(edge.get("source_script_ids"))
    return {"nodes": nodes, "edges": edges}


def get_entities(project_id: str) -> list[dict[str, Any]]:
    entities = list_rows("SELECT * FROM entities WHERE project_id = ? ORDER BY type, name", (project_id,))
    for entity in entities:
        entity["images"] = list_rows("SELECT * FROM entity_images WHERE entity_id = ? ORDER BY created_at DESC", (entity["id"],))
        normalize_entity(entity)
    return entities


def build_frame_prompt(description: str, entity_names: list[str], refs: list[str]) -> str:
    names = ", ".join(entity_names) if entity_names else "no fixed entity"
    references = ", ".join(refs) if refs else "no reference image"
    return f"{description}\nReferenced entities: {names}\nReference images: {references}"


def generate_frames(project_id: str, script_ids: list[str]) -> list[dict[str, Any]]:
    scripts = get_scripts_by_ids(project_id, script_ids)
    if not scripts:
        raise HTTPException(status_code=400, detail="Please select at least one script")
    entities = get_entities(project_id)
    now = now_iso()
    selected_ids = [script["id"] for script in scripts]
    selection_key = dump_ids(selected_ids)
    with connect() as conn:
        placeholders = ",".join(["?"] * len(selected_ids))
        conn.execute(
            f"DELETE FROM frames WHERE project_id = ? AND scope = ? AND script_id IN ({placeholders})",
            tuple([project_id, selection_key, *selected_ids]),
        )
        frame_index = 1
        for script in scripts:
            chunks = split_script(script["content"])
            for source in chunks:
                related = [entity for entity in entities if entity["name"] in source] or entities[: min(3, len(entities))]
                entity_ids = [entity["id"] for entity in related]
                image_ids: list[str] = []
                image_urls: list[str] = []
                names: list[str] = []
                for entity in related:
                    names.append(entity["name"])
                    if entity.get("main_image_id"):
                        image_ids.append(entity["main_image_id"])
                        image = conn.execute("SELECT image_url FROM entity_images WHERE id = ?", (entity["main_image_id"],)).fetchone()
                        if image:
                            image_urls.append(image["image_url"])
                description = f"第 {frame_index} 帧：{source}。画面需要突出 {', '.join(names) if names else '核心情绪'}。"
                prompt = build_frame_prompt(description, names, image_urls)
                conn.execute(
                    """
                    INSERT INTO frames (
                        id, project_id, script_id, script_title, scope, frame_index, source_text,
                        description, camera, mood, entity_ids, reference_image_ids,
                        prompt, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        project_id,
                        script["id"],
                        script["title"],
                        selection_key,
                        frame_index,
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
                frame_index += 1
        conn.execute("UPDATE projects SET status = ?, progress = ?, updated_at = ? WHERE id = ?", ("frames_ready", 85, now, project_id))
    return get_frames(project_id, selection_key, selected_ids)


def get_frames(project_id: str, scope: str | None = None, script_ids: list[str] | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM frames WHERE project_id = ?"
    params: list[Any] = [project_id]
    if scope:
        query += " AND scope = ?"
        params.append(scope)
    if script_ids:
        placeholders = ",".join(["?"] * len(script_ids))
        query += f" AND script_id IN ({placeholders})"
        params.extend(script_ids)
    query += " ORDER BY scope, frame_index"
    frames = list_rows(query, tuple(params))
    entities = {entity["id"]: entity for entity in get_entities(project_id)}
    for frame in frames:
        frame["entity_ids"] = json_list(frame["entity_ids"])
        frame["reference_image_ids"] = json_list(frame["reference_image_ids"])
        frame["entities"] = [entities[eid] for eid in frame["entity_ids"] if eid in entities]
    return frames


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^\w\-.一-龥]+", "_", value, flags=re.UNICODE).strip("_")
    return cleaned[:60] or "asset"


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
    script_id = str(uuid.uuid4()) if payload.script else None
    script_content = payload.script or ""
    title = payload.title or clean_title(script_content) if script_content else payload.title or "未命名项目"
    script_title = payload.script_title or clean_title(script_content) if script_content else payload.script_title or "第一幕"
    now = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO projects (
                id, title, script, content_type, active_script_id, status,
                progress, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, title, script_content, payload.content_type, script_id, "draft", 10, now, now),
        )
        if script_id:
            conn.execute(
                """
                INSERT INTO project_scripts (
                    id, project_id, title, content, content_type, order_index, status,
                    word_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (script_id, project_id, script_title, script_content, payload.content_type, 1, "draft", len(script_content), now, now),
            )
    return project_detail(project_id)


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate) -> dict[str, Any]:
    get_project(project_id)
    with connect() as conn:
        conn.execute("UPDATE projects SET title = ?, updated_at = ? WHERE id = ?", (payload.title, now_iso(), project_id))
    return project_detail(project_id)


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, str]:
    get_project(project_id)
    with connect() as conn:
        for table in ["exports", "frames", "entity_images", "entities", "graph_edges", "graph_nodes", "project_scripts"]:
            conn.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    project_paths = [UPLOAD_DIR / project_id, GENERATED_DIR / project_id, EXPORT_DIR / project_id]
    for path in project_paths:
        if path.exists() and path.resolve().is_relative_to(DATA_DIR):
            shutil.rmtree(path)
    return {"status": "deleted"}


@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    rows = list_rows("SELECT * FROM projects ORDER BY updated_at DESC")
    return [get_project(row["id"]) for row in rows]


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str) -> dict[str, Any]:
    project = get_project(project_id)
    active_script = get_script(project["active_script_id"]) if project.get("active_script_id") else None
    project["active_script"] = active_script
    project["scripts"] = get_scripts(project_id)
    project["graph"] = get_graph(project_id)
    project["entities"] = get_entities(project_id)
    project["frames"] = get_frames(project_id)
    project["exports"] = list_rows("SELECT * FROM exports WHERE project_id = ? ORDER BY created_at DESC", (project_id,))
    return project


@app.post("/api/projects/{project_id}/scripts")
def add_script(project_id: str, payload: ScriptCreate) -> dict[str, Any]:
    get_project(project_id)
    script_id = str(uuid.uuid4())
    now = now_iso()
    order_index = scalar("SELECT COUNT(*) FROM project_scripts WHERE project_id = ?", (project_id,)) + 1
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO project_scripts (
                id, project_id, title, content, content_type, order_index, status,
                word_count, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                script_id,
                project_id,
                payload.title or clean_title(payload.content),
                payload.content,
                payload.content_type,
                order_index,
                "draft",
                len(payload.content),
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE projects SET active_script_id = ?, status = ?, progress = ?, updated_at = ? WHERE id = ?",
            (script_id, "draft", 20, now, project_id),
        )
    return project_detail(project_id)


@app.get("/api/projects/{project_id}/scripts")
def list_scripts(project_id: str) -> list[dict[str, Any]]:
    get_project(project_id)
    return get_scripts(project_id)


@app.patch("/api/projects/{project_id}/scripts/{script_id}")
def update_script(project_id: str, script_id: str, payload: ScriptUpdate) -> dict[str, Any]:
    script = get_script(script_id)
    if script["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Script does not belong to project")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return script
    allowed = {"title", "content", "content_type"}
    assignments = [f"{key} = ?" for key in updates if key in allowed]
    values = [updates[key] for key in updates if key in allowed]
    if "content" in updates and updates["content"] is not None:
        assignments.append("word_count = ?")
        values.append(len(updates["content"]))
        assignments.append("status = ?")
        values.append("draft")
    assignments.append("updated_at = ?")
    values.append(now_iso())
    values.append(script_id)
    with connect() as conn:
        conn.execute(f"UPDATE project_scripts SET {', '.join(assignments)} WHERE id = ?", tuple(values))
        conn.execute("UPDATE projects SET updated_at = ?, active_script_id = ? WHERE id = ?", (now_iso(), script_id, project_id))
    return get_script(script_id)


@app.delete("/api/projects/{project_id}/scripts/{script_id}")
def delete_script(project_id: str, script_id: str) -> dict[str, Any]:
    script = get_script(script_id)
    if script["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Script does not belong to project")
    with connect() as conn:
        conn.execute("DELETE FROM project_scripts WHERE id = ?", (script_id,))
        conn.execute("DELETE FROM frames WHERE project_id = ? AND script_id = ?", (project_id, script_id))
        next_script = conn.execute(
            "SELECT id FROM project_scripts WHERE project_id = ? ORDER BY order_index, created_at LIMIT 1",
            (project_id,),
        ).fetchone()
        conn.execute(
            "UPDATE projects SET active_script_id = ?, updated_at = ? WHERE id = ?",
            (next_script["id"] if next_script else None, now_iso(), project_id),
        )
    return project_detail(project_id)


@app.patch("/api/projects/{project_id}/active-script")
def set_active_script(project_id: str, payload: ActiveScriptUpdate) -> dict[str, Any]:
    script = get_script(payload.script_id)
    if script["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Script does not belong to project")
    with connect() as conn:
        conn.execute("UPDATE projects SET active_script_id = ?, updated_at = ? WHERE id = ?", (payload.script_id, now_iso(), project_id))
    return project_detail(project_id)


@app.post("/api/projects/{project_id}/analyze")
def analyze_active_project_script(project_id: str) -> dict[str, Any]:
    return analyze_project_graph(project_id)


@app.post("/api/projects/{project_id}/scripts/{script_id}/analyze")
def analyze_project_script(project_id: str, script_id: str) -> dict[str, Any]:
    return analyze_project_graph(project_id)


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
    allowed = {"name", "type", "description", "visual_description", "prompt", "status", "main_image_id"}
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


@app.post("/api/entities/{entity_id}/merge")
def merge_entity(entity_id: str, payload: EntityMerge) -> dict[str, Any]:
    source = entity_with_images(entity_id)
    target = entity_with_images(payload.target_entity_id)
    if source["project_id"] != target["project_id"]:
        raise HTTPException(status_code=400, detail="Entities belong to different projects")
    source_scripts = source["source_script_ids"] + target["source_script_ids"]
    now = now_iso()
    with connect() as conn:
        conn.execute(
            """
            UPDATE entities
            SET source_script_ids = ?, occurrence_count = ?, updated_at = ?
            WHERE id = ?
            """,
            (dump_ids(source_scripts), source["occurrence_count"] + target["occurrence_count"], now, target["id"]),
        )
        conn.execute("UPDATE entity_images SET entity_id = ? WHERE entity_id = ?", (target["id"], source["id"]))
        conn.execute("UPDATE graph_nodes SET entity_id = ?, change_state = ? WHERE entity_id = ?", (target["id"], "updated", source["id"]))
        conn.execute("DELETE FROM entities WHERE id = ?", (source["id"],))
    return entity_with_images(target["id"])


@app.post("/api/entities/{entity_id}/images")
def generate_entity_image(entity_id: str, payload: EntityImageCreate) -> dict[str, Any]:
    entity = entity_with_images(entity_id)
    prompt = payload.prompt or entity.get("prompt") or default_prompt(entity)
    image_id = str(uuid.uuid4())
    path = create_svg_image(entity, prompt, image_id)
    image_url = storage_url(path)
    now = now_iso()
    with connect() as conn:
        existing_count = conn.execute("SELECT COUNT(*) FROM entity_images WHERE entity_id = ?", (entity_id,)).fetchone()[0]
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
            conn.execute("UPDATE entities SET main_image_id = ?, status = ?, updated_at = ? WHERE id = ?", (image_id, "image_ready", now, entity_id))
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
        existing_count = conn.execute("SELECT COUNT(*) FROM entity_images WHERE entity_id = ?", (entity_id,)).fetchone()[0]
        is_main = 1 if existing_count == 0 else 0
        conn.execute(
            """
            INSERT INTO entity_images (
                id, entity_id, project_id, image_url, file_path, prompt,
                reference_image_url, is_main, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (image_id, entity_id, entity["project_id"], image_url, str(target), prompt, image_url, is_main, now),
        )
        if is_main:
            conn.execute("UPDATE entities SET main_image_id = ?, status = ?, updated_at = ? WHERE id = ?", (image_id, "image_ready", now, entity_id))
    return entity_with_images(entity_id)


@app.delete("/api/entity-images/{image_id}")
def delete_entity_image(image_id: str) -> dict[str, Any]:
    with connect() as conn:
        image = row_to_dict(conn.execute("SELECT * FROM entity_images WHERE id = ?", (image_id,)).fetchone())
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        entity = row_to_dict(conn.execute("SELECT * FROM entities WHERE id = ?", (image["entity_id"],)).fetchone())
        if not entity:
            raise HTTPException(status_code=404, detail="Entity not found")
        conn.execute("DELETE FROM entity_images WHERE id = ?", (image_id,))
        replacement = conn.execute(
            "SELECT id FROM entity_images WHERE entity_id = ? ORDER BY created_at DESC LIMIT 1",
            (image["entity_id"],),
        ).fetchone()
        if entity.get("main_image_id") == image_id:
            conn.execute(
                "UPDATE entities SET main_image_id = ?, status = ?, updated_at = ? WHERE id = ?",
                (
                    replacement["id"] if replacement else None,
                    "image_ready" if replacement else "image_pending",
                    now_iso(),
                    image["entity_id"],
                ),
            )
    file_path = Path(image["file_path"])
    if file_path.exists() and file_path.resolve().is_relative_to(DATA_DIR):
        file_path.unlink()
    return entity_with_images(image["entity_id"])


@app.post("/api/projects/{project_id}/frames/generate")
def create_frames(project_id: str, payload: FrameGenerate) -> list[dict[str, Any]]:
    get_project(project_id)
    return generate_frames(project_id, payload.script_ids)


@app.get("/api/projects/{project_id}/frames")
def frames(
    project_id: str,
    scope: str | None = Query(default=None),
    script_ids: list[str] | None = Query(default=None, alias="scriptIds"),
) -> list[dict[str, Any]]:
    get_project(project_id)
    return get_frames(project_id, scope, script_ids)


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
        allowed = {"description", "camera", "mood", "entity_ids", "reference_image_ids"}
        assignments = [f"{key} = ?" for key in updates if key in allowed]
        values = [updates[key] for key in updates if key in allowed]
        assignments.append("updated_at = ?")
        values.append(now_iso())
        values.append(frame_id)
        conn.execute(f"UPDATE frames SET {', '.join(assignments)} WHERE id = ?", tuple(values))
    return next(item for item in get_frames(frame["project_id"], frame["scope"], [frame["script_id"]]) if item["id"] == frame_id)


@app.post("/api/projects/{project_id}/export")
def export_project(project_id: str, payload: ExportCreate) -> dict[str, Any]:
    project = project_detail(project_id)
    scripts = get_scripts_by_ids(project_id, payload.script_ids)
    if not scripts:
        raise HTTPException(status_code=400, detail="Please select at least one script")
    selected_ids = [script["id"] for script in scripts]
    selection_key = dump_ids(selected_ids)
    frames_to_export = get_frames(project_id, selection_key, selected_ids)
    if not frames_to_export:
        frames_to_export = generate_frames(project_id, selected_ids)
    export_id = str(uuid.uuid4())
    target_dir = EXPORT_DIR / project_id
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{export_id}.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        manifest = {
            "project": project,
            "scope": selection_key,
            "scriptIds": selected_ids,
            "frameCount": len(frames_to_export),
        }
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("project.json", json.dumps(project, ensure_ascii=False, indent=2))
        archive.writestr("knowledge-graph/graph.json", json.dumps(project["graph"], ensure_ascii=False, indent=2))
        archive.writestr("scripts/all-scripts.md", "\n\n".join([f"# {script['title']}\n\n{script['content']}" for script in project["scripts"]]))
        archive.writestr("scripts/selected-scripts.md", "\n\n".join([f"# {script['title']}\n\n{script['content']}" for script in scripts]))
        for frame in frames_to_export:
            frame_dir = f"frames/{frame['frame_index']:03d}"
            scene_md = "\n".join(
                [
                    f"# Frame {frame['frame_index']:03d}",
                    "",
                    f"- 所属剧本：{frame.get('script_title') or ''}",
                    f"- 原文片段：{frame['source_text']}",
                    f"- 镜头语言：{frame.get('camera') or ''}",
                    f"- 情绪氛围：{frame.get('mood') or ''}",
                    "",
                    "## 场景描述",
                    frame["description"],
                    "",
                    "## 完整提示词",
                    frame["prompt"],
                    "",
                    "## 关联实体",
                    "\n".join([f"- {entity['name']} ({entity['type']})" for entity in frame["entities"]]) or "- 无",
                ]
            )
            archive.writestr(f"{frame_dir}/scene.md", scene_md)
            frame_json = {key: value for key, value in frame.items() if key != "entities"}
            frame_json["entityImageFiles"] = []
            for entity in frame["entities"]:
                main = next((image for image in entity["images"] if image["id"] == entity.get("main_image_id")), None)
                if not main and entity["images"]:
                    main = entity["images"][0]
                if not main:
                    continue
                file_path = Path(main["file_path"])
                if not file_path.exists():
                    continue
                suffix = file_path.suffix or ".png"
                image_name = f"{safe_filename(entity['type'])}_{safe_filename(entity['name'])}{suffix}"
                archive.write(file_path, f"{frame_dir}/entities/{image_name}")
                frame_json["entityImageFiles"].append(image_name)
            archive.writestr(f"{frame_dir}/frame.json", json.dumps(frame_json, ensure_ascii=False, indent=2))
    file_url = storage_url(target)
    now = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO exports (id, project_id, script_id, scope, file_url, file_path, frame_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (export_id, project_id, None, selection_key, file_url, str(target), len(frames_to_export), now),
        )
        conn.execute("UPDATE projects SET status = ?, progress = ?, updated_at = ? WHERE id = ?", ("export_ready", 100, now, project_id))
    return {"id": export_id, "file_url": file_url, "scope": selection_key, "frame_count": len(frames_to_export), "created_at": now}


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
