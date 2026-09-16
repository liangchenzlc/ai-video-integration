ALTER TABLE projects ADD COLUMN budget_warning_percent INTEGER NOT NULL DEFAULT 80 CHECK(budget_warning_percent BETWEEN 1 AND 100);
ALTER TABLE projects ADD COLUMN execution_mode TEXT CHECK(execution_mode IN ('synthetic','real'));
CREATE TABLE stage_budgets (
 stage TEXT PRIMARY KEY CHECK(stage IN ('story','image','video','speech','lipsync','music','sfx','check')),
 limit_micro_cny INTEGER NOT NULL CHECK(limit_micro_cny>=0)
) STRICT;
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
 expires_at TEXT, requested_at TEXT NOT NULL, error_code TEXT, result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)), UNIQUE(task_id,step_id,ordinal)
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

INSERT INTO stage_budgets VALUES ('story',0),('image',0),('video',0),('speech',0),('lipsync',0),('music',0),('sfx',0),('check',0);
