BEGIN IMMEDIATE;
CREATE TABLE projects (
 id TEXT PRIMARY KEY, singleton INTEGER NOT NULL DEFAULT 1 UNIQUE CHECK(singleton=1),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 120), format_version INTEGER NOT NULL CHECK(format_version>=1),
 revision INTEGER NOT NULL DEFAULT 0 CHECK(revision>=0), event_sequence INTEGER NOT NULL DEFAULT 0 CHECK(event_sequence>=0),
 aspect TEXT NOT NULL CHECK(aspect IN ('16:9','9:16')), resolution TEXT NOT NULL CHECK(resolution IN ('720p','1080p')),
 fps_n INTEGER NOT NULL CHECK(fps_n IN (24,25,30)), fps_d INTEGER NOT NULL DEFAULT 1 CHECK(fps_d=1),
 target_ms INTEGER NOT NULL CHECK(target_ms>0), budget_micro_cny INTEGER NOT NULL DEFAULT 0 CHECK(budget_micro_cny>=0), saved_at TEXT
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
PRAGMA user_version=2;
COMMIT;