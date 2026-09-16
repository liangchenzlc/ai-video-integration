"""T08: actual revision/service boundaries, without provider calls or other modules."""

import copy

import pytest

from app.storage import revisions
from app.storage.database import connect
from app.storage.errors import ProjectError
from tests.storage.production_fixtures import ProductionProject
from tests.storage.production_fixtures import production_project as production_project
from tests.storage.test_drafts import opened as opened
from tests.storage.test_versions import adopt, candidate


def test_complete_recording_capacity_counts_internal_pause_once(
    production_project: ProductionProject,
) -> None:
    project = production_project
    assert project.timing() == {
        "requiredMs": 6400,
        "plannedMs": 6000,
        "shortageMs": 400,
        "method": "measured",
        "suitable": False,
    }
    # Removing outer margins leaves the complete recording, including its existing pause.
    assert project.timing(0, 0) == {
        "requiredMs": 5200,
        "plannedMs": 6000,
        "shortageMs": 0,
        "method": "measured",
        "suitable": True,
    }
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        assert db.execute("SELECT count(*) FROM service_calls").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM cost_entries").fetchone()[0] == 0


def test_estimated_timing_is_labelled_and_missing_recording_blocks_capacity(
    production_project: ProductionProject,
) -> None:
    project = production_project
    estimated = copy.deepcopy(project.speech)
    estimated["timingMethod"] = "estimated"
    _, revision_id = candidate(
        project.opened,
        kind="speech",
        content=estimated,
        artifact=project.speech_artifact_id,
        parent=project.speech_revision_id,
    )
    adopt(project.opened, project.speech_artifact_id, revision_id)
    project.speech_revision_id = revision_id
    assert project.timing()["method"] == "estimated"
    project.audio_path.rename(project.audio_path.with_suffix(".offline"))
    with pytest.raises(ProjectError, match="MEDIA_MISSING"):
        project.timing()


def test_subtitle_edit_is_independent_and_difference_flag_is_verified(
    production_project: ProductionProject,
) -> None:
    project = production_project
    subtitle = project.subtitle("别怕，", True)
    artifact, revision_id = candidate(project.opened, kind="subtitle", content=subtitle)
    adopt(project.opened, artifact, revision_id)
    with connect(project.opened[1] / "project.sqlite3", "ro") as db:
        assert revisions.get(db, project.speech_revision_id)["payload"]["content"]["text"] == "别怕"
        assert revisions.get(db, revision_id)["payload"]["content"]["cues"][0]["text"] == "别怕，"
        assert (
            revisions.artifact(db, project.speech_artifact_id)["adoptedRevisionId"]
            == project.speech_revision_id
        )
        assert db.execute("SELECT count(*) FROM service_calls").fetchone()[0] == 0
    subtitle["cues"][0]["differsFromDialogue"] = False
    with pytest.raises(ProjectError, match="SUBTITLE_DIFFERENCE_MISMATCH"):
        candidate(project.opened, kind="subtitle", content=subtitle)


def test_recording_duration_cannot_be_shortened_in_formal_payload(
    production_project: ProductionProject,
) -> None:
    content = copy.deepcopy(production_project.speech)
    content["measuredMs"] = 4700
    content["voicedRanges"] = []
    with pytest.raises(ProjectError, match="AUDIO_DURATION_MISMATCH"):
        candidate(production_project.opened, kind="speech", content=content)


@pytest.mark.parametrize("kind", ["speech", "subtitle"])
def test_time_range_outside_actual_recording_cannot_be_formalized(
    production_project: ProductionProject,
    kind: str,
) -> None:
    project = production_project
    content = copy.deepcopy(project.speech) if kind == "speech" else project.subtitle()
    if kind == "speech":
        content["voicedRanges"][-1]["endMs"] = 5201
    else:
        content["cues"][0]["time"]["endMs"] = 5201
    with pytest.raises(ProjectError, match="TIME_RANGE_INVALID"):
        candidate(project.opened, kind=kind, content=content)


@pytest.mark.parametrize("kind", ["speech", "subtitle"])
def test_word_precision_requires_actual_word_timestamp_source(
    production_project: ProductionProject,
    kind: str,
) -> None:
    project = production_project
    content = copy.deepcopy(project.speech) if kind == "speech" else project.subtitle()
    content["timingMethod"] = "provider_word"
    with pytest.raises(ProjectError, match="WORD_TIMING_UNAVAILABLE"):
        candidate(project.opened, kind=kind, content=content)
