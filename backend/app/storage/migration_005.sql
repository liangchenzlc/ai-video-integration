CREATE TABLE artifacts (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('story','asset','shot','speech','subtitle','timeline','observation')),
 adopted_revision_id TEXT, confirmed_revision_id TEXT, needs_update INTEGER NOT NULL DEFAULT 0 CHECK(needs_update IN (0,1)),
 FOREIGN KEY(id,adopted_revision_id) REFERENCES revisions(artifact_id,id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY(id,confirmed_revision_id) REFERENCES revisions(artifact_id,id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE revisions (
 id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(id) DEFERRABLE INITIALLY DEFERRED,
 parent_id TEXT, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), content_hash TEXT NOT NULL CHECK(length(content_hash)=64), created_at TEXT NOT NULL,
 UNIQUE(artifact_id,id), FOREIGN KEY(artifact_id,parent_id) REFERENCES revisions(artifact_id,id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TRIGGER immutable_revision_update BEFORE UPDATE ON revisions BEGIN SELECT RAISE(ABORT,'revisions are immutable'); END;
CREATE TRIGGER immutable_revision_delete BEFORE DELETE ON revisions BEGIN SELECT RAISE(ABORT,'revisions are immutable'); END;
CREATE TABLE revision_media (
 revision_id TEXT NOT NULL REFERENCES revisions(id), media_id TEXT NOT NULL REFERENCES media_files(id), role TEXT NOT NULL,
 ordinal INTEGER NOT NULL DEFAULT 0 CHECK(ordinal>=0), PRIMARY KEY(revision_id,media_id,role,ordinal)
) STRICT;
CREATE TABLE dependencies (
 from_revision_id TEXT NOT NULL REFERENCES revisions(id), to_revision_id TEXT NOT NULL REFERENCES revisions(id),
 semantic_scope TEXT NOT NULL CHECK(semantic_scope IN ('identityVisual','dialogueAudio','subtitleTiming','referenceInput','requirementCoverage','revealTiming','timelinePlacement','mix','export')),
 PRIMARY KEY(from_revision_id,to_revision_id,semantic_scope), CHECK(from_revision_id!=to_revision_id)
) STRICT;
CREATE INDEX dependent_revision_idx ON dependencies(to_revision_id);
CREATE TABLE task_inputs (
 task_id TEXT NOT NULL REFERENCES user_tasks(id), revision_id TEXT NOT NULL REFERENCES revisions(id), PRIMARY KEY(task_id,revision_id)
) STRICT;
CREATE TABLE adoptions (
 id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL REFERENCES artifacts(id), from_revision_id TEXT, to_revision_id TEXT NOT NULL,
 before_snapshot_json TEXT NOT NULL CHECK(json_valid(before_snapshot_json)), undone INTEGER NOT NULL DEFAULT 0 CHECK(undone IN (0,1)),
 operation_id TEXT NOT NULL UNIQUE REFERENCES operations(id) DEFERRABLE INITIALLY DEFERRED,
 after_snapshot_json TEXT NOT NULL CHECK(json_valid(after_snapshot_json)),
 FOREIGN KEY(artifact_id,from_revision_id) REFERENCES revisions(artifact_id,id), FOREIGN KEY(artifact_id,to_revision_id) REFERENCES revisions(artifact_id,id)
) STRICT;
CREATE TABLE check_runs (
 id TEXT PRIMARY KEY, report_json TEXT NOT NULL CHECK(json_valid(report_json)),
 outcome TEXT NOT NULL CHECK(outcome IN ('pass','fail','unknown','not_applicable')), created_at TEXT NOT NULL
) STRICT;
CREATE TABLE checks (
 id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, revision_id TEXT NOT NULL, baseline_revision_id TEXT REFERENCES revisions(id),
 rule_id TEXT NOT NULL, rule_version TEXT NOT NULL, method TEXT NOT NULL CHECK(method IN ('local','ai','human')),
 severity TEXT NOT NULL CHECK(severity IN ('blocking','unknown_required','deviation','advice')),
 status TEXT NOT NULL CHECK(status IN ('open','fixing','recheck','resolved','accepted_deviation')), evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)),
 check_run_id TEXT NOT NULL REFERENCES check_runs(id),
 FOREIGN KEY(artifact_id,revision_id) REFERENCES revisions(artifact_id,id), CHECK(status!='accepted_deviation' OR severity IN ('deviation','advice'))
) STRICT;
CREATE INDEX checks_revision_idx ON checks(revision_id,status);

CREATE TRIGGER immutable_artifact_kind BEFORE UPDATE OF kind ON artifacts WHEN NEW.kind!=OLD.kind BEGIN SELECT RAISE(ABORT,'artifact kind is immutable'); END;

CREATE TABLE task_plan_inputs (
 plan_id TEXT NOT NULL REFERENCES task_plans(id), revision_id TEXT NOT NULL REFERENCES revisions(id),
 snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)), PRIMARY KEY(plan_id,revision_id)
) STRICT;
CREATE TRIGGER immutable_plan_input_update BEFORE UPDATE ON task_plan_inputs BEGIN SELECT RAISE(ABORT,'plan inputs are immutable'); END;
CREATE TRIGGER immutable_plan_input_delete BEFORE DELETE ON task_plan_inputs BEGIN SELECT RAISE(ABORT,'plan inputs are immutable'); END;
