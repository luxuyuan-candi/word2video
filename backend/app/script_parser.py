from __future__ import annotations

import re
from dataclasses import dataclass, field


ENTITY_LEXICON: dict[str, list[str]] = {
    "character": [
        "小明",
        "小红",
        "少年",
        "女孩",
        "男孩",
        "老师",
        "主角",
        "老人",
        "摄影师",
        "母亲",
        "父亲",
        "队长",
        "医生",
        "学生",
        "机器人",
    ],
    "object": [
        "钥匙",
        "手机",
        "盒子",
        "书",
        "信",
        "机器",
        "产品",
        "背包",
        "手表",
        "相机",
        "门",
        "电脑",
        "地图",
        "灯",
        "飞船",
        "药瓶",
    ],
    "scene": [
        "城市",
        "房间",
        "办公室",
        "学校",
        "街道",
        "森林",
        "海边",
        "实验室",
        "广场",
        "天台",
        "书店",
        "走廊",
        "教室",
        "车站",
        "医院",
        "餐厅",
    ],
    "concept": [
        "星河",
        "梦想",
        "危险",
        "秘密",
        "回忆",
        "希望",
        "恐惧",
        "温暖",
        "孤独",
        "未来",
        "危机",
        "胜利",
    ],
}

ACTION_VERBS = [
    "发现",
    "告诉",
    "来到",
    "进入",
    "穿过",
    "举起",
    "打开",
    "寻找",
    "看见",
    "拿起",
    "放下",
    "奔跑",
    "追赶",
    "离开",
    "回到",
    "变成",
    "出现",
    "消失",
    "交给",
    "保护",
    "启动",
]

SCENE_HINTS = ["在", "来到", "进入", "走进", "穿过", "回到"]
OBJECT_HINTS = ["发现", "拿起", "举起", "打开", "带着", "交给", "启动", "使用"]


@dataclass
class ParsedEntity:
    name: str
    type: str
    description: str
    mentions: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ParsedEvent:
    key: str
    name: str
    description: str
    source_text: str
    script_id: str
    script_title: str
    order: int
    entity_names: list[str]
    action: str


@dataclass
class ParsedRelation:
    source_key: str
    target_key: str
    relation: str
    description: str
    source_text: str
    script_id: str


@dataclass
class ParsedGraph:
    entities: list[ParsedEntity]
    events: list[ParsedEvent]
    relations: list[ParsedRelation]


def split_sentences(content: str) -> list[str]:
    sentences = re.split(r"(?<=[。！？.!?])\s*|\n+", content)
    return [sentence.strip() for sentence in sentences if sentence and sentence.strip()]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", text)


def detect_action(sentence: str) -> str:
    for verb in ACTION_VERBS:
        if verb in sentence:
            return verb
    return "叙事推进"


def extract_candidate_names(sentence: str) -> list[str]:
    names: list[str] = []
    for pattern in [r"小[\u4e00-\u9fa5]", r"老[\u4e00-\u9fa5]", r"阿[\u4e00-\u9fa5]", r"[\u4e00-\u9fa5]{1,4}(?:老师|医生|队长|同学|经理)"]:
        for match in re.findall(pattern, sentence):
            if match not in names:
                names.append(match)
    return names


def infer_dynamic_entities(sentence: str) -> list[tuple[str, str]]:
    inferred: list[tuple[str, str]] = []
    for name in extract_candidate_names(sentence):
        inferred.append(("character", name))
    for hint in SCENE_HINTS:
        if hint in sentence:
            tail = sentence.split(hint, 1)[-1]
            candidate = re.split(r"[，。！？,.!?]|发现|看见|遇到|打开|举起|告诉", tail)[0]
            candidate = candidate.strip()[:8]
            if 2 <= len(candidate) <= 8 and not any(word in candidate for word in ["他", "她", "它", "这"]):
                inferred.append(("scene", candidate))
    for hint in OBJECT_HINTS:
        if hint in sentence:
            tail = sentence.split(hint, 1)[-1]
            candidate = re.split(r"[，。！？,.!?]|来到|进入|穿过|告诉|变成", tail)[0]
            candidate = candidate.strip()[:8]
            if 1 < len(candidate) <= 8 and not any(word in candidate for word in ["他", "她", "它", "城市"]):
                inferred.append(("object", candidate))
    return inferred


def entity_description(entity_type: str, name: str) -> str:
    labels = {
        "character": "人物",
        "object": "物品",
        "scene": "场景",
        "concept": "概念",
    }
    return f"剧本中识别到的{labels.get(entity_type, '对象')}“{name}”，用于构建项目级知识图谱和后续视觉一致性管理。"


def collect_sentence_entities(sentence: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for entity_type, words in ENTITY_LEXICON.items():
        for word in words:
            if word in sentence and (entity_type, word) not in found:
                found.append((entity_type, word))
    for inferred in infer_dynamic_entities(sentence):
        if inferred not in found:
            found.append(inferred)
    return found


def summarize_event(sentence: str, order: int) -> str:
    compact = normalize_text(sentence)
    return compact[:16] or f"事件{order}"


def event_key(script_id: str, order: int) -> str:
    return f"event:{script_id}:{order}"


def entity_key(name: str) -> str:
    return f"entity:{name}"


def relation_for_entity(entity_type: str) -> str:
    return {
        "character": "参与",
        "scene": "发生于",
        "object": "关联道具",
        "concept": "表达",
    }.get(entity_type, "关联")


def parse_project_scripts(scripts: list[dict[str, str]]) -> ParsedGraph:
    entities: dict[str, ParsedEntity] = {}
    events: list[ParsedEvent] = []
    relations: list[ParsedRelation] = []
    previous_event_key: str | None = None
    last_character: str | None = None
    global_order = 1

    for script in scripts:
        script_id = script["id"]
        script_title = script["title"]
        for sentence_index, sentence in enumerate(split_sentences(script["content"]), start=1):
            sentence_entities = collect_sentence_entities(sentence)
            if last_character and any(pronoun in sentence for pronoun in ["他", "她"]):
                sentence_entities.append(("character", last_character))
            unique_entities: list[tuple[str, str]] = []
            for entity in sentence_entities:
                if entity not in unique_entities:
                    unique_entities.append(entity)
            for entity_type, name in unique_entities:
                key = entity_key(name)
                if key not in entities:
                    entities[key] = ParsedEntity(name=name, type=entity_type, description=entity_description(entity_type, name))
                entities[key].mentions.append((script_id, sentence))
                if entity_type == "character":
                    last_character = name

            action = detect_action(sentence)
            key = event_key(script_id, sentence_index)
            event = ParsedEvent(
                key=key,
                name=summarize_event(sentence, global_order),
                description=f"《{script_title}》第 {sentence_index} 个叙事事件：{sentence}",
                source_text=sentence,
                script_id=script_id,
                script_title=script_title,
                order=global_order,
                entity_names=[name for _, name in unique_entities],
                action=action,
            )
            events.append(event)

            if previous_event_key:
                relations.append(
                    ParsedRelation(
                        source_key=previous_event_key,
                        target_key=key,
                        relation="然后",
                        description="事件按剧本顺序连续发生。",
                        source_text=sentence,
                        script_id=script_id,
                    )
                )
            previous_event_key = key

            for entity_type, name in unique_entities:
                relation = relation_for_entity(entity_type)
                relations.append(
                    ParsedRelation(
                        source_key=entity_key(name),
                        target_key=key,
                        relation=relation,
                        description=f"{name} 与事件“{event.name}”存在“{relation}”关系。",
                        source_text=sentence,
                        script_id=script_id,
                    )
                )

            characters = [name for entity_type, name in unique_entities if entity_type == "character"]
            scenes = [name for entity_type, name in unique_entities if entity_type == "scene"]
            objects = [name for entity_type, name in unique_entities if entity_type == "object"]
            for character in characters:
                for scene in scenes:
                    relations.append(
                        ParsedRelation(entity_key(character), entity_key(scene), "位于", f"{character} 出现在 {scene}。", sentence, script_id)
                    )
                for obj in objects:
                    relations.append(
                        ParsedRelation(entity_key(character), entity_key(obj), "使用/接触", f"{character} 与 {obj} 发生交互。", sentence, script_id)
                    )
            global_order += 1

    if not entities:
        entities[entity_key("主角")] = ParsedEntity("主角", "character", entity_description("character", "主角"))
        entities[entity_key("主要场景")] = ParsedEntity("主要场景", "scene", entity_description("scene", "主要场景"))

    return ParsedGraph(entities=list(entities.values()), events=events, relations=relations)
