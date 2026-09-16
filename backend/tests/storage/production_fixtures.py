"""Small actual project/PCM fixtures shared by the staged production module tests."""

import hashlib
import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.services.projects import ProjectService
from app.storage.database import connect
from tests.storage.test_versions import adopt, candidate, context

Json = dict[str, Any]


@dataclass
class ProductionProject:
    opened: tuple[ProjectService, Path, Json]
    speaker_id: str
    dialogue_id: str
    scene_id: str
    shot_id: str
    shot_revision_id: str
    media_id: str
    audio_path: Path
    speech_artifact_id: str
    speech_revision_id: str
    speech: Json

    @property
    def service(self) -> ProjectService:
        return self.opened[0]

    @property
    def args(self) -> tuple[str, str, int]:
        return context(self.opened)[1]

    def timing(self, before: int = 600, after: int = 600) -> Json:
        return self.service._production_audio.timing_check(
            *self.args,
            {
                "shotRevisionId": self.shot_revision_id,
                "speechRevisionIds": [self.speech_revision_id],
                "beforeMs": before,
                "afterMs": after,
            },
        )

    def subtitle(self, text: str = "别怕", differs: bool = False) -> Json:
        return {
            "audioRevisionId": self.speech_revision_id,
            "timingMethod": "manual",
            "cues": [
                {
                    "id": str(uuid4()),
                    "dialogueId": self.dialogue_id,
                    "text": text,
                    "time": {"startMs": 0, "endMs": 5200},
                    "differsFromDialogue": differs,
                }
            ],
        }


@pytest.fixture
def production_project(
    opened: tuple[ProjectService, Path, Json], request: pytest.FixtureRequest
) -> ProductionProject:
    _, directory, _ = opened
    speaker, speaker_revision = candidate(
        opened,
        kind="asset",
        content={
            "assetType": "character",
            "name": "说话人",
            "identityAnchors": ["成年"],
            "allowedChanges": [],
            "states": [],
            "references": [],
        },
    )
    adopt(opened, speaker, speaker_revision)
    scene_id, dialogue_id, shot_id = (str(uuid4()) for _ in range(3))
    story, story_revision = candidate(
        opened,
        kind="story",
        content={
            "sourceText": "别怕",
            "brief": "保留对白",
            "inputType": "script",
            "scenes": [
                {
                    "id": scene_id,
                    "title": "第一场",
                    "action": "说话",
                    "plannedMs": 6000,
                    "locationAssetId": None,
                }
            ],
            "dialogues": [
                {
                    "id": dialogue_id,
                    "speakerAssetId": speaker,
                    "text": "别怕",
                    "delivery": getattr(request, "param", "VO"),
                    "requirementIds": [],
                    "sceneId": scene_id,
                }
            ],
        },
    )
    adopt(opened, story, story_revision)
    shot, shot_revision = candidate(
        opened,
        kind="shot",
        content={
            "shotId": shot_id,
            "purpose": "完整对白",
            "sceneId": scene_id,
            "assetRevisionIds": [speaker_revision],
            "requirementIds": [],
            "startState": "安静",
            "events": [],
            "endState": "说完",
            "camera": "固定",
            "subjectHand": "none",
            "plannedMs": 6000,
            "dialogueIds": [dialogue_id],
            "references": [],
            "videoMediaId": None,
            "pickupOfShotId": None,
            "use": "original",
        },
    )
    adopt(opened, shot, shot_revision)
    media_id = str(uuid4())
    audio_path = directory / "media" / (media_id + ".wav")
    audio_path.parent.mkdir(exist_ok=True)
    with wave.open(str(audio_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        # Engineering tone only: 2 s signal, 0.5 s silence, then 2.7 s signal.
        # The recorded duration is real; this fixture makes no natural-speech claim.
        period = b"".join(
            struct.pack("<h", round(2000 * math.sin(2 * math.pi * index / 160)))
            for index in range(160)
        )
        output.writeframes(period * 200 + b"\x00\x00" * 8000 + period * 270)
    with wave.open(str(audio_path), "rb") as recording:
        measured_ms = recording.getnframes() * 1000 // recording.getframerate()
    digest = hashlib.sha256(audio_path.read_bytes()).hexdigest()
    with connect(directory / "project.sqlite3") as db, db:
        db.execute(
            "INSERT INTO media_files VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                media_id,
                "media/" + audio_path.name,
                digest,
                audio_path.stat().st_size,
                "audio/wav",
                measured_ms,
                None,
                None,
                "available",
                "imported",
                "{}",
            ),
        )
    speech = {
        "dialogueId": dialogue_id,
        "text": "别怕",
        "speakerAssetId": speaker,
        "mediaId": media_id,
        "measuredMs": measured_ms,
        "voicedRanges": [{"startMs": 0, "endMs": 2000}, {"startMs": 2500, "endMs": 5200}],
        "timingMethod": "manual",
        "voicePreset": "imported-recording",
        "pronunciationNotes": "",
    }
    speech_artifact, speech_revision = candidate(opened, kind="speech", content=speech)
    adopt(opened, speech_artifact, speech_revision)
    return ProductionProject(
        opened,
        speaker,
        dialogue_id,
        scene_id,
        shot_id,
        shot_revision,
        media_id,
        audio_path,
        speech_artifact,
        speech_revision,
        speech,
    )
