CREATE TABLE rights_evidence (
 id TEXT PRIMARY KEY, media_id TEXT NOT NULL REFERENCES media_files(id),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), updated_at TEXT NOT NULL
) STRICT;
CREATE TABLE rights_verifications (
 id TEXT PRIMARY KEY, evidence_id TEXT NOT NULL REFERENCES rights_evidence(id),
 media_hash TEXT NOT NULL CHECK(length(media_hash)=64),
 evidence_hashes_json TEXT NOT NULL CHECK(json_valid(evidence_hashes_json)),
 explanation TEXT NOT NULL, created_at TEXT NOT NULL
) STRICT;
ALTER TABLE uploads ADD COLUMN checksum_sha256 TEXT;
CREATE TABLE render_plans (
 id TEXT PRIMARY KEY, timeline_revision_id TEXT NOT NULL REFERENCES revisions(id),
 plan_json TEXT NOT NULL CHECK(json_valid(plan_json)), input_hash TEXT NOT NULL CHECK(length(input_hash)=64)
) STRICT;
CREATE TABLE exports (
 id TEXT PRIMARY KEY, timeline_revision_id TEXT NOT NULL REFERENCES revisions(id),
 job_id TEXT NOT NULL UNIQUE REFERENCES local_jobs(id),
 state TEXT NOT NULL CHECK(state IN ('pending','complete','failed','cancelled')),
 media_id TEXT REFERENCES media_files(id), input_hash TEXT NOT NULL CHECK(length(input_hash)=64)
) STRICT;
CREATE TRIGGER immutable_render_plan_update BEFORE UPDATE ON render_plans
 BEGIN SELECT RAISE(ABORT,'render plans are immutable'); END;
CREATE TRIGGER immutable_render_plan_delete BEFORE DELETE ON render_plans
 BEGIN SELECT RAISE(ABORT,'render plans are immutable'); END;
CREATE TABLE check_decisions (
 id TEXT PRIMARY KEY, issue_id TEXT NOT NULL REFERENCES checks(id),
 action TEXT NOT NULL CHECK(action IN ('accept_deviation','request_recheck','attach_evidence')),
 reason TEXT NOT NULL, evidence_media_ids_json TEXT NOT NULL CHECK(json_valid(evidence_media_ids_json)),
 created_at TEXT NOT NULL, operation_id TEXT NOT NULL REFERENCES operations(id) DEFERRABLE INITIALLY DEFERRED
) STRICT;
