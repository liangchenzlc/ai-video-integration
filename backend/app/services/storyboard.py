"""Project-bound storyboard reads and receipt-backed mutations."""

from typing import TYPE_CHECKING, Any

from app.storage import storyboard

if TYPE_CHECKING:
    from app.services.projects import ProjectService

Json = dict[str, Any]


class StoryboardService:
    def __init__(self, owner: "ProjectService") -> None:
        self.owner = owner

    def list(self, project_id: str, session_id: str, window_id: int) -> Json:
        return self.owner._versions.read(
            project_id,
            session_id,
            window_id,
            lambda db, _: storyboard.summaries(db),
        )

    def coverage(self, project_id: str, session_id: str, window_id: int) -> Json:
        return self.owner._versions.read(
            project_id,
            session_id,
            window_id,
            lambda db, _: storyboard.coverage(db),
        )

    def reorder(self, project_id: str, session_id: str, window_id: int, command: Json) -> Json:
        return self.owner._versions.write(
            project_id,
            session_id,
            window_id,
            command,
            "reorderShots",
            {"shotIds"},
            None,
            lambda db, _project, payload: storyboard.reorder(db, payload),
        )

    def verify(self, project_id: str, session_id: str, window_id: int, command: Json) -> Json:
        return self.owner._versions.write(
            project_id,
            session_id,
            window_id,
            command,
            "verifyReference",
            {"draftId", "mediaId", "role", "matchesPurpose", "note"},
            None,
            lambda db, _project, payload: storyboard.verify(db, payload),
        )
