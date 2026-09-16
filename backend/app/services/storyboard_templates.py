"""Local organization of adopted facts, never inference or production authorization."""

import json
import sqlite3
from typing import TYPE_CHECKING, Any, Literal

from app.storage import revisions, storyboard
from app.storage.errors import ProjectError
from app.storage.task_plans import identifier

if TYPE_CHECKING:
    from app.services.projects import ProjectService

VERSION = "t07-local-2026-09-16-v1"
Json = dict[str, Any]


def preview_for_project(
    owner: "ProjectService",
    project_id: str,
    session_id: str,
    window_id: int,
    shot_id: str,
    phase: Literal["image", "video"],
) -> Json:
    with owner._mutex:
        return owner._versions.read(
            project_id,
            session_id,
            window_id,
            lambda db, _: build_preview(db, shot_id, phase),
        )


def build_preview(db: sqlite3.Connection, shot_id: str, phase: str) -> Json:
    identifier(shot_id)
    if phase not in {"image", "video"}:
        raise ProjectError("VALIDATION_FAILED", 422)
    if db.execute("PRAGMA user_version").fetchone()[0] < 7:
        raise ProjectError("PROJECT_VERSION_UNSUPPORTED")
    matches = [
        row
        for row in db.execute(
            "SELECT a.*,r.payload_json FROM artifacts a JOIN revisions r "
            "ON r.id=a.adopted_revision_id WHERE a.kind='shot'"
        )
        if json.loads(row["payload_json"])["content"]["shotId"] == shot_id
    ]
    if len(matches) != 1:
        raise ProjectError("INPUT_INCOMPLETE", 422)
    shot = matches[0]
    rid = shot["adopted_revision_id"]
    content = json.loads(shot["payload_json"])["content"]
    blockers: list[str] = []
    source_ids = [rid]
    if shot["confirmed_revision_id"] != rid or shot["needs_update"]:
        blockers.append("镜头文字尚未确认，或有待更新内容。")
    if revisions.stale_inputs(db, rid):
        blockers.append("镜头引用的已采用基准发生变化，请重新核对。")
    facts = [f"观看目的：{content['purpose']}", f"起点：{content['startState']}"]
    if phase == "image":
        facts.append("画面只表达起点的一个冻结瞬间；动作完成态不得替代动作首帧。")
    else:
        carriers = {"visual": "画面", "audio": "声音", "subtitle": "字幕", "screenText": "画内文字"}
        observers = {"physical": "物理状态", "character": "人物知情", "audience": "观众可知"}
        facts.extend(
            f"动作（{carriers[event['carrier']]}／{observers[event['observer']]}）：{event['text']}"
            for event in content["events"]
        )
        facts.append(f"终点：{content['endState']}")
    facts.extend(
        [
            f"摄影与光线：{content['camera']}",
            f"主体用手：{content['subjectHand']}",
            f"计划时长：{content['plannedMs']} 毫秒",
        ]
    )
    story_rows = db.execute(
        "SELECT DISTINCT a.*,r.payload_json FROM dependencies d "
        "JOIN revisions old ON old.id=d.from_revision_id JOIN artifacts a ON a.id=old.artifact_id "
        "JOIN revisions r ON r.id=a.adopted_revision_id "
        "WHERE d.to_revision_id=? AND a.kind='story'",
        (rid,),
    ).fetchall()
    for row in story_rows:
        story = json.loads(row["payload_json"])["content"]
        story_rid = row["adopted_revision_id"]
        if story_rid is not None and story_rid not in source_ids:
            source_ids.append(story_rid)
        if story_rid is None or row["confirmed_revision_id"] != story_rid or row["needs_update"]:
            blockers.append("故事文字尚未确认或需要更新。")
        for dialogue in story["dialogues"]:
            if dialogue["id"] in content["dialogueIds"]:
                facts.append(f"对白原句（{dialogue['delivery']}）：{dialogue['text']}")
        for requirement in story["requirements"]:
            if requirement["id"] in content["requirementIds"]:
                facts.append(f"内容要求（{requirement['category']}）：{requirement['text']}")
    refs = [(rid, reference) for reference in content["references"]]
    ordinals = dict(db.execute("SELECT shot_id,ordinal FROM storyboard_shots"))
    for asset_id in content["assetRevisionIds"]:
        asset = revisions.get(db, asset_id)
        state = revisions.artifact(db, asset["artifactId"])
        source_ids.append(asset_id)
        if (
            state["adoptedRevisionId"] != asset_id
            or state["confirmedRevisionId"] != asset_id
            or state["needsUpdate"]
        ):
            blockers.append("所需资产尚未按镜头引用的版本采用并确认。")
        if state["adoptedRevisionId"] != asset_id:
            continue
        asset_content = asset["payload"]["content"]
        facts.append(f"资产 {asset_content['name']}：{'；'.join(asset_content['identityAnchors'])}")
        if asset_content["allowedChanges"]:
            facts.append("允许变化：" + "；".join(asset_content["allowedChanges"]))
        for persistent in asset_content["states"]:
            start = ordinals.get(persistent["fromShotId"])
            end = ordinals.get(persistent["throughShotId"])
            current = ordinals.get(shot_id)
            if start is None or end is None or current is None or start > end:
                blockers.append("资产持续状态的镜头范围需要重新核对。")
            elif start <= current <= end:
                facts.append(f"持续状态：{persistent['description']}；原因：{persistent['reason']}")
        refs.extend((asset_id, reference) for reference in asset_content["references"])
    for reference_revision, ref in refs:
        if not storyboard.adopted_reference_usable(db, reference_revision, ref):
            blockers.append("参考尚未核对用途、已缺失或内容发生变化。")
            continue
        facts.append(
            f"参考用途：{ref['role']}；保持：{'；'.join(ref['keep'])}；"
            f"忽略：{'；'.join(ref['ignore'])}"
        )
    if phase == "video":
        blockers.extend(
            [
                "正式配音与局部预演证据尚未接入，请在声音和预演模块完成核对。",
                "真实视频接口及本次预算授权尚未完成，不能启动试片。",
            ]
        )
        if content["videoMediaId"]:
            blockers.append("现有视频缺少完整试片基准证据，暂不能自动认定可复用。")
    else:
        blockers.append("这里只组织本地制作依据；生成仍需另行预览并授权任务。")
    facts.append("不添加剧情之外的字幕；剧情画内文字按内容要求单独保留并核对。")
    prompt = "\n".join(facts)
    if len(prompt) > 100000:
        raise ProjectError("INPUT_SIZE_LIMIT", 422)
    return {
        "templateId": f"shot-{phase}",
        "templateVersion": VERSION,
        "prompt": prompt,
        "sourceRevisionIds": list(dict.fromkeys(source_ids)),
        "blockers": list(dict.fromkeys(blockers)),
        "reusableVideoMediaId": None,
    }
