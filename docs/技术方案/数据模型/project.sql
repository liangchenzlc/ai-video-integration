-- Design baseline 0.1.0. Final relationship model, NOT a production migration.
-- Production installs only the owning module's migrations after a backup.
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;

CREATE TABLE projects (
 id TEXT PRIMARY KEY, singleton INTEGER NOT NULL DEFAULT 1 UNIQUE CHECK(singleton=1),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120), format_version INTEGER NOT NULL CHECK(format_version>=1),
 revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0), event_sequence INTEGER NOT NULL DEFAULT 0 CHECK(event_sequence>=0),
 aspect TEXT NOT NULL CHECK(aspect IN ('16:9','9:16')), resolution TEXT NOT NULL CHECK(resolution IN ('720p','1080p')),
 fps_n INTEGER NOT NULL CHECK(fps_n IN (24,25,30)), fps_d INTEGER NOT NULL DEFAULT 1 CHECK(fps_d=1),
 target_ms INTEGER NOT NULL CHECK(target_ms>0), budget_micro_cny INTEGER NOT NULL DEFAULT 0 CHECK(budget_micro_cny>=0), saved_at TEXT,
 budget_warning_percent INTEGER NOT NULL DEFAULT 80 CHECK(budget_warning_percent BETWEEN 1 AND 100),
 execution_mode TEXT CHECK(execution_mode IS NULL OR execution_mode IN ('synthetic','real'))
) STRICT;
CREATE TABLE operations (
 id TEXT PRIMARY KEY, request_hash TEXT NOT NULL CHECK(length(request_hash)=64), operation_name TEXT NOT NULL,
 committed_revision INTEGER NOT NULL CHECK(committed_revision>=0), resource_id TEXT NOT NULL,
 receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json)), created_at TEXT NOT NULL
) STRICT;
CREATE TABLE media_files (
 id TEXT PRIMARY KEY, relative_path TEXT NOT NULL UNIQUE CHECK(length(relative_path)>0 AND relative_path NOT LIKE '/%' AND instr(relative_path,':')=0 AND instr(relative_path,'\')=0 AND instr('/'||relative_path||'/','/../')=0),
 sha256 TEXT NOT NULL CHECK(length(sha256)=64), byte_length INTEGER NOT NULL CHECK(byte_length>0), mime TEXT NOT NULL,
 duration_ms INTEGER CHECK(duration_ms>0), width INTEGER CHECK(width>0), height INTEGER CHECK(height>0),
 availability TEXT NOT NULL CHECK(availability IN ('staging','available','missing','quarantined')),
 provenance TEXT NOT NULL CHECK(provenance IN ('imported','generated','derived','synthetic')), source_json TEXT NOT NULL CHECK(json_valid(source_json))
) STRICT;
CREATE INDEX media_hash_idx ON media_files(sha256);
CREATE TABLE import_intents (
 id TEXT PRIMARY KEY, media_id TEXT NOT NULL UNIQUE, source_kind TEXT NOT NULL CHECK(source_kind IN ('local','remote','derived')),
 expected_hash TEXT, staging_path TEXT NOT NULL, target_path TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('planned','writing','verified','renamed','registered','quarantined')),
 operation_id TEXT NOT NULL REFERENCES operations(id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE TABLE drafts (
 id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL, base_revision_id TEXT,
 kind TEXT NOT NULL CHECK(kind IN ('story','asset','shot','speech','subtitle','timeline','observation')),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), saved_at TEXT NOT NULL
) STRICT;
CREATE TABLE local_jobs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('import','probe','animatic','export','diagnostic','local_check')),
 state TEXT NOT NULL CHECK(state IN ('queued','running','succeeded','failed','cancelled')),
 heavy INTEGER NOT NULL CHECK(heavy IN (0,1)), active INTEGER NOT NULL CHECK(active IN (0,1)),
 snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)), result_id TEXT, error_code TEXT,
 operation_id TEXT NOT NULL REFERENCES operations(id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
CREATE UNIQUE INDEX one_heavy_job ON local_jobs(active) WHERE active=1 AND heavy=1;
CREATE TABLE stage_budgets (
 stage TEXT PRIMARY KEY CHECK(stage IN ('story','image','video','speech','lipsync','music','sfx','check')),
 limit_micro_cny INTEGER NOT NULL CHECK(limit_micro_cny>=0)
) STRICT;
-- Introduced in T03 before T04 budgets; no FK to a future migration.
CREATE TABLE stage_models (phase TEXT PRIMARY KEY CHECK(phase IN ('story_adaptation','story_outline','story_scene','story_dialogue','image_character','image_location','image_prop','image_keyframe','video','speech','lipsync','music','sfx','check')), capability_id TEXT NOT NULL, capability_version TEXT NOT NULL) STRICT;
CREATE TABLE task_plans (
 id TEXT PRIMARY KEY, object_id TEXT NOT NULL, stage TEXT NOT NULL REFERENCES stage_budgets(stage),
 plan_json TEXT NOT NULL CHECK(json_valid(plan_json)), input_hash TEXT NOT NULL CHECK(length(input_hash)=64),
 maximum_micro_cny INTEGER NOT NULL CHECK(maximum_micro_cny>=0), expires_at TEXT NOT NULL,
 execution_mode TEXT NOT NULL CHECK(execution_mode IN ('synthetic','real'))
) STRICT;
CREATE TABLE user_tasks (
 id TEXT PRIMARY KEY, plan_id TEXT NOT NULL UNIQUE REFERENCES task_plans(id),
 state TEXT NOT NULL CHECK(state IN ('pending','running','complete','partial','result_unknown','pending_download','failed')),
 active INTEGER NOT NULL CHECK(active IN (0,1)), observation_stopped INTEGER NOT NULL DEFAULT 0 CHECK(observation_stopped IN (0,1)),
 authorized_maximum_micro_cny INTEGER NOT NULL CHECK(authorized_maximum_micro_cny>=0), event_sequence INTEGER NOT NULL DEFAULT 0 CHECK(event_sequence>=0)
) STRICT;
CREATE UNIQUE INDEX one_active_task ON user_tasks(active) WHERE active=1;
CREATE TABLE planned_steps (
 id TEXT PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES task_plans(id), ordinal INTEGER NOT NULL CHECK(ordinal>=0),
 purpose TEXT NOT NULL CHECK(purpose IN ('create','revise','precheck')), maximum_calls INTEGER NOT NULL CHECK(maximum_calls BETWEEN 1 AND 16),
 maximum_micro_cny INTEGER NOT NULL CHECK(maximum_micro_cny>=0), snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)), UNIQUE(plan_id,ordinal)
) STRICT;
CREATE TABLE service_calls (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES user_tasks(id), step_id TEXT NOT NULL REFERENCES planned_steps(id),
 ordinal INTEGER NOT NULL CHECK(ordinal>=0), submission_token TEXT NOT NULL UNIQUE,
 provider_id TEXT NOT NULL, model_id TEXT NOT NULL, region TEXT NOT NULL, remote_task_id TEXT,
 state TEXT NOT NULL CHECK(state IN ('prepared','submitting','running','result_unknown','pending_download','succeeded','failed','cancelled')),
 request_hash TEXT NOT NULL CHECK(length(request_hash)=64), request_snapshot_json TEXT NOT NULL CHECK(json_valid(request_snapshot_json)),
 expires_at TEXT, UNIQUE(task_id,step_id,ordinal)
) STRICT;
CREATE INDEX call_remote_idx ON service_calls(provider_id,region,remote_task_id);
CREATE TRIGGER call_step_matches_plan BEFORE INSERT ON service_calls
WHEN (SELECT plan_id FROM user_tasks WHERE id=NEW.task_id) != (SELECT plan_id FROM planned_steps WHERE id=NEW.step_id)
BEGIN SELECT RAISE(ABORT,'step does not belong to task plan'); END;
CREATE TABLE call_events (
 id INTEGER PRIMARY KEY, call_id TEXT NOT NULL REFERENCES service_calls(id), event_sequence INTEGER NOT NULL,
 event_type TEXT NOT NULL, facts_json TEXT NOT NULL CHECK(json_valid(facts_json)), created_at TEXT NOT NULL, UNIQUE(call_id,event_sequence)
) STRICT;
CREATE TRIGGER immutable_call_event_update BEFORE UPDATE ON call_events BEGIN SELECT RAISE(ABORT,'call events are append only'); END;
CREATE TRIGGER immutable_call_event_delete BEFORE DELETE ON call_events BEGIN SELECT RAISE(ABORT,'call events are append only'); END;
CREATE TABLE cost_entries (
 call_id TEXT PRIMARY KEY REFERENCES service_calls(id), state TEXT NOT NULL CHECK(state IN ('pending','settled')),
 reserved_micro_cny INTEGER NOT NULL CHECK(reserved_micro_cny>=0), settled_micro_cny INTEGER CHECK(settled_micro_cny>=0), basis TEXT NOT NULL DEFAULT '',
 CHECK((state='pending' AND settled_micro_cny IS NULL) OR (state='settled' AND settled_micro_cny IS NOT NULL AND length(basis)>0))
) STRICT;
CREATE VIEW charged_costs AS SELECT call_id, CASE state WHEN 'settled' THEN settled_micro_cny ELSE reserved_micro_cny END AS amount_micro_cny FROM cost_entries;
CREATE TABLE external_expenses (
 id TEXT PRIMARY KEY, category TEXT NOT NULL CHECK(category IN ('storage','transfer','procurement')),
 state TEXT NOT NULL CHECK(state IN ('estimated','pending','settled')), amount_micro_cny INTEGER NOT NULL CHECK(amount_micro_cny>=0), basis TEXT NOT NULL
) STRICT;
CREATE TABLE uploads (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES user_tasks(id), media_id TEXT NOT NULL REFERENCES media_files(id),
 storage_profile_id TEXT NOT NULL, object_key TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('uploading','available','delete_pending','deleted','failed')),
 signed_until TEXT, retain_until TEXT, UNIQUE(storage_profile_id,object_key)
) STRICT;
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
 operation_id TEXT NOT NULL UNIQUE REFERENCES operations(id),
 FOREIGN KEY(artifact_id,from_revision_id) REFERENCES revisions(artifact_id,id), FOREIGN KEY(artifact_id,to_revision_id) REFERENCES revisions(artifact_id,id)
) STRICT;
CREATE TABLE shots (
 id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL UNIQUE REFERENCES artifacts(id), ordinal INTEGER NOT NULL UNIQUE CHECK(ordinal>=0),
 pickup_of_shot_id TEXT REFERENCES shots(id), use TEXT NOT NULL CHECK(use IN ('original','supplement','alternate')), CHECK(pickup_of_shot_id IS NULL OR pickup_of_shot_id!=id)
) STRICT;
CREATE TABLE timeline_indexes (
 revision_id TEXT NOT NULL REFERENCES revisions(id), clip_id TEXT NOT NULL, media_id TEXT REFERENCES media_files(id), content_revision_id TEXT REFERENCES revisions(id),
 shot_id TEXT REFERENCES shots(id), start_ms INTEGER NOT NULL CHECK(start_ms>=0), in_ms INTEGER NOT NULL CHECK(in_ms>=0), out_ms INTEGER NOT NULL, duration_ms INTEGER NOT NULL CHECK(duration_ms>0),
 PRIMARY KEY(revision_id,clip_id), CHECK(out_ms>in_ms), CHECK(media_id IS NOT NULL OR content_revision_id IS NOT NULL)
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
CREATE TABLE check_decisions (
 id TEXT PRIMARY KEY, check_id TEXT NOT NULL REFERENCES checks(id), action TEXT NOT NULL CHECK(action IN ('accept_deviation','request_recheck','attach_evidence','resolve')),
 reason TEXT NOT NULL, evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)), created_at TEXT NOT NULL
) STRICT;
CREATE TABLE rights_evidence (
 id TEXT PRIMARY KEY, media_id TEXT NOT NULL REFERENCES media_files(id), source TEXT NOT NULL, intended_use TEXT NOT NULL,
 evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json)), state TEXT NOT NULL CHECK(state IN ('unverified','verified','recheck'))
) STRICT;
CREATE TABLE exports (
 id TEXT PRIMARY KEY, timeline_revision_id TEXT NOT NULL REFERENCES revisions(id), job_id TEXT NOT NULL UNIQUE REFERENCES local_jobs(id),
 state TEXT NOT NULL CHECK(state IN ('pending','complete','failed','cancelled')), media_id TEXT REFERENCES media_files(id),
 input_hash TEXT NOT NULL CHECK(length(input_hash)=64), manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json)), CHECK(state!='complete' OR media_id IS NOT NULL)
) STRICT;
