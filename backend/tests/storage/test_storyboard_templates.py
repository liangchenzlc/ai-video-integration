from typing import Any
from uuid import uuid4

import pytest
from app.services.storyboard_templates import build_preview
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.test_drafts import opened as opened
from tests.storage.test_versions import adopt, candidate


def test_local_templates_use_adopted_facts_and_keep_trial_gates_closed(opened: Any) -> None:
    scene, shot, event = (str(uuid4()) for _ in range(3))
    story_content = {
        "sourceText": "A traveller opens a door.",
        "brief": "One scene",
        "inputType": "script",
        "scenes": [
            {
                "id": scene,
                "title": "Door",
                "action": "Open the door",
                "plannedMs": 3000,
                "locationAssetId": None,
            }
        ],
    }
    story_artifact, story_revision = candidate(opened, content=story_content)
    adopt(opened, story_artifact, story_revision)
    shot_content = {
        "shotId": shot,
        "sceneId": scene,
        "purpose": "Reveal the traveller",
        "assetRevisionIds": [],
        "requirementIds": [],
        "startState": "The door is closed",
        "events": [
            {
                "id": event,
                "text": "The traveller opens the door",
                "time": {"startMs": 0, "endMs": 3000},
                "requirementIds": [],
                "carrier": "visual",
                "observer": "audience",
            }
        ],
        "endState": "The door is open",
        "camera": "A static wide shot with soft light",
        "subjectHand": "left",
        "plannedMs": 3000,
        "dialogueIds": [],
        "references": [],
        "videoMediaId": None,
        "pickupOfShotId": None,
        "use": "original",
    }
    artifact, revision = candidate(opened, kind="shot", content=shot_content)
    adopt(opened, artifact, revision)
    with connect(opened[1] / "project.sqlite3", "ro") as db:
        before = db.execute("SELECT revision FROM projects").fetchone()[0]
        image = build_preview(db, shot, "image")
        video = build_preview(db, shot, "video")
        assert db.execute("SELECT revision FROM projects").fetchone()[0] == before
        assert image["templateId"] == "shot-image"
        assert "The door is closed" in image["prompt"]
        assert "The traveller opens the door" not in image["prompt"]
        assert "The traveller opens the door" in video["prompt"]
        assert revision in video["sourceRevisionIds"]
        assert story_revision in video["sourceRevisionIds"]
        assert video["blockers"] and video["reusableVideoMediaId"] is None
        assert db.execute("SELECT count(*) FROM user_tasks").fetchone()[0] == 0


def test_prompt_requires_an_adopted_shot_and_known_phase(opened: Any) -> None:
    with connect(opened[1] / "project.sqlite3", "ro") as db:
        with pytest.raises(ProjectError, match="INPUT_INCOMPLETE"):
            build_preview(db, str(uuid4()), "video")
        with pytest.raises(ProjectError, match="VALIDATION_FAILED"):
            build_preview(db, str(uuid4()), "unexpected")
