"""Scope-aware adoption graph and narrow reversible snapshots."""

import json
import sqlite3
from typing import Any

from app.storage import revisions
from app.storage.errors import ProjectError
from app.storage.semantic_scopes import SCOPES, changed_scopes
from app.storage.settings import canonical

Json = dict[str, Any]


def validate_graph(db: sqlite3.Connection, artifact_id: str, revision_id: str) -> None:
    # Validate the graph of active object choices, replacing only the proposed adoption.
    active = {
        row["id"]: row["adopted_revision_id"]
        for row in db.execute(
            "SELECT id,adopted_revision_id FROM artifacts WHERE adopted_revision_id IS NOT NULL"
        )
    }
    active[artifact_id] = revision_id
    graph: dict[str, set[str]] = {key: set() for key in active}
    for target, rid in active.items():
        for row in db.execute(
            "SELECT r.artifact_id FROM dependencies d JOIN revisions r ON "
            "r.id=d.from_revision_id WHERE d.to_revision_id=?",
            (rid,),
        ):
            graph.setdefault(row[0], set()).add(target)
    # Kahn's traversal avoids depending on Python's recursion limit for long projects.
    incoming = dict.fromkeys(graph, 0)
    for children in graph.values():
        for child in children:
            incoming[child] += 1
    ready = [node for node, count in incoming.items() if count == 0]
    visited = 0
    while ready:
        node = ready.pop()
        visited += 1
        for child in graph[node]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    if visited != len(graph):
        raise ProjectError("DEPENDENCY_CYCLE", 422)


def impact(db: sqlite3.Connection, artifact_id: str, revision_id: str) -> Json:
    target = revisions.get(db, revision_id, artifact_id)
    obj = revisions.artifact(db, artifact_id)
    old = revisions.get(db, obj["adoptedRevisionId"]) if obj["adoptedRevisionId"] else None
    validate_graph(db, artifact_id, revision_id)
    scopes = changed_scopes(old, target)
    affected: set[str] = set()
    # A dependent may still reference an older revision of this object after an earlier
    # adoption; use artifact identity to retain its unresolved update obligation.
    pending = [(artifact_id, scopes)]
    visited: set[str] = set()
    while pending:
        source, allowed = pending.pop()
        if source in visited:
            continue
        visited.add(source)
        for row in db.execute(
            "SELECT target.artifact_id,d.semantic_scope FROM dependencies d JOIN revisions "
            "source ON source.id=d.from_revision_id JOIN revisions target ON "
            "target.id=d.to_revision_id JOIN artifacts a ON a.id=target.artifact_id AND "
            "a.adopted_revision_id=target.id WHERE source.artifact_id=?",
            (source,),
        ):
            if row["semantic_scope"] in allowed and row["artifact_id"] != artifact_id:
                affected.add(row["artifact_id"])
                pending.append((row["artifact_id"], set(SCOPES)))
    return {
        "artifactId": artifact_id,
        "fromRevisionId": obj["adoptedRevisionId"],
        "toRevisionId": revision_id,
        "affectedArtifactIds": sorted(affected),
        "affectedScopes": sorted(scopes),
        "estimatedExtraMicroCny": None,
        "requiredChecks": ["structural", "references"],
    }


def check_locks(db: sqlite3.Connection, artifact_ids: list[str]) -> None:
    locked = {
        row[0]
        for row in db.execute(
            "SELECT r.artifact_id FROM task_inputs i JOIN revisions r ON r.id=i.revision_id "
            "JOIN user_tasks t ON t.id=i.task_id WHERE t.active=1"
        )
    }
    if locked.intersection(artifact_ids):
        raise ProjectError("INPUT_LOCKED")


def snapshot(db: sqlite3.Connection, artifact_ids: list[str]) -> Json:
    # Extend this narrow snapshot when T07 shot placement and T09 timeline indexes exist.
    # Immutable revision dependencies already preserve the adopted relation graph.
    items = [revisions.artifact(db, key) for key in sorted(artifact_ids)]
    for item in items:
        item.pop("latestAdoptionId")
    return {"artifacts": items}


def restore(db: sqlite3.Connection, saved: Json) -> None:
    for obj in saved["artifacts"]:
        db.execute(
            "UPDATE artifacts SET adopted_revision_id=?,confirmed_revision_id=?,needs_update=? "
            "WHERE id=?",
            (
                obj["adoptedRevisionId"],
                obj["confirmedRevisionId"],
                int(obj["needsUpdate"]),
                obj["id"],
            ),
        )


def undo(db: sqlite3.Connection, adoption_id: str) -> str:
    row = db.execute("SELECT * FROM adoptions WHERE id=?", (adoption_id,)).fetchone()
    nearest = db.execute(
        "SELECT id FROM adoptions WHERE undone=0 ORDER BY rowid DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise ProjectError("OBJECT_NOT_FOUND", 404)
    if row["undone"] or nearest is None or nearest[0] != adoption_id:
        raise ProjectError("UNDO_CONFLICT")
    before, after = json.loads(row["before_snapshot_json"]), json.loads(row["after_snapshot_json"])
    keys = [item["id"] for item in before["artifacts"]]
    check_locks(db, keys)
    if canonical(snapshot(db, keys)) != canonical(after):
        raise ProjectError("UNDO_CONFLICT")
    restore(db, before)
    db.execute("UPDATE adoptions SET undone=1 WHERE id=?", (adoption_id,))
    return adoption_id
