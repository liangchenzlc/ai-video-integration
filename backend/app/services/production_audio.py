"""Session-bound local T08/T10/T11 operations using existing short transactions."""

from typing import TYPE_CHECKING, Any

from app.services.video_inputs import readiness
from app.storage import capabilities, production_audio
from app.storage.errors import ProjectError

if TYPE_CHECKING:
    from app.services.projects import ProjectService

Json = dict[str, Any]


class ProductionAudioService:
    def __init__(self, owner: "ProjectService") -> None:
        self.owner = owner

    def timing_check(self, project_id: str, session_id: str, window_id: int, payload: Json) -> Json:
        with self.owner._mutex:
            return self.owner._versions.read(
                project_id,
                session_id,
                window_id,
                lambda db, _: production_audio.timing_check(db, payload),
            )

    def video_readiness(
        self, project_id: str, session_id: str, window_id: int, payload: Json
    ) -> Json:
        with self.owner._mutex:
            # Resolve the session before inspecting the application capability registry.
            self.owner._draft_session(project_id, session_id, window_id)
            try:
                profile = capabilities.get(self.owner._application, payload["capabilityId"])
            except ProjectError as error:
                if error.code != "CAPABILITY_UNAVAILABLE":
                    raise
                profile = None
            return self.owner._versions.read(
                project_id, session_id, window_id, lambda db, _: readiness(db, payload, profile)
            )

    def list_rights(self, project_id: str, session_id: str, window_id: int) -> Json:
        with self.owner._mutex:
            return self.owner._versions.read(
                project_id, session_id, window_id, lambda db, _: production_audio.list_rights(db)
            )

    def save_rights(
        self, project_id: str, session_id: str, window_id: int, evidence_id: str, command: Json
    ) -> Json:
        with self.owner._mutex:
            return self.owner._versions.write(
                project_id,
                session_id,
                window_id,
                command,
                "saveRightsEvidence",
                {"evidence"},
                evidence_id,
                lambda db, _, payload: production_audio.save_rights(db, evidence_id, payload),
            )

    def ducking(self, project_id: str, session_id: str, window_id: int, payload: Json) -> Json:
        with self.owner._mutex:
            return self.owner._versions.read(
                project_id,
                session_id,
                window_id,
                lambda db, _: production_audio.ducking(db, payload),
            )
