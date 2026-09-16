"""Pure old/new payload classification shared by adoption and input validation."""

from typing import Any

Json = dict[str, Any]

SCOPES = {
    "identityVisual",
    "dialogueAudio",
    "subtitleTiming",
    "referenceInput",
    "requirementCoverage",
    "revealTiming",
    "timelinePlacement",
    "mix",
    "export",
}


def changed_scopes(before: Json | None, after: Json) -> set[str]:
    if before is None:
        return set(SCOPES)
    if before["contentHash"] == after["contentHash"]:
        return set()
    kind = after["payload"]["kind"]
    old, new = before["payload"]["content"], after["payload"]["content"]
    changed = {key for key in set(old) | set(new) if old.get(key) != new.get(key)}
    if kind == "asset":
        return {"identityVisual", "referenceInput", "export"}
    if kind == "subtitle":
        # A text edit doesn't travel backwards into speech. Cue timing changes also require
        # a timing review of downstream consumers.
        scopes = {"export", "timelinePlacement"}
        if [c.get("time") for c in old["cues"]] != [c.get("time") for c in new["cues"]]:
            scopes.add("subtitleTiming")
        return scopes
    if kind == "speech":
        return {"dialogueAudio", "subtitleTiming", "mix", "export", "timelinePlacement"}
    if kind == "story":
        if changed - {"dialogues", "scenes", "outline", "requirements", "approvalLevel"}:
            # Changes to source prose, brief or adaptation notes cannot be classified
            # reliably by a local rule; keep every actual downstream review obligation.
            return set(SCOPES)
        scopes = {"requirementCoverage", "referenceInput", "export"}
        if changed & {"dialogues", "sourceText"}:
            scopes |= {"dialogueAudio", "subtitleTiming"}
        if changed & {"scenes", "outline"}:
            scopes |= {"revealTiming", "timelinePlacement"}
        return scopes
    return set(SCOPES)
