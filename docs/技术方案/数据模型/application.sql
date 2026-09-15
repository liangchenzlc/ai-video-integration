-- Application-wide design store. Never copy this database into a project.
PRAGMA foreign_keys=ON;
CREATE TABLE settings (singleton INTEGER PRIMARY KEY CHECK(singleton=1), revision INTEGER NOT NULL CHECK(revision>=0), ffmpeg_path TEXT, ffmpeg_probe_json TEXT CHECK(ffmpeg_probe_json IS NULL OR json_valid(ffmpeg_probe_json))) STRICT;
CREATE TABLE credentials (id TEXT PRIMARY KEY, provider_id TEXT NOT NULL UNIQUE, dpapi_ciphertext BLOB NOT NULL, masked_suffix TEXT NOT NULL CHECK(length(masked_suffix)=4)) STRICT;
-- Session-only secrets exist only in process memory, never as rows with plaintext.
CREATE TABLE capabilities (id TEXT PRIMARY KEY, version TEXT NOT NULL, profile_json TEXT NOT NULL CHECK(json_valid(profile_json)), checked_at TEXT NOT NULL) STRICT;
CREATE TABLE storage_profiles (id TEXT PRIMARY KEY, provider_id TEXT NOT NULL, bucket TEXT NOT NULL, region TEXT NOT NULL, credential_id TEXT NOT NULL REFERENCES credentials(id), retention_hours INTEGER NOT NULL CHECK(retention_hours BETWEEN 1 AND 168)) STRICT;
CREATE TABLE recent_projects (project_id TEXT PRIMARY KEY, directory TEXT NOT NULL UNIQUE, last_opened_at TEXT NOT NULL) STRICT;
CREATE TABLE global_operations (id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, operation_name TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('prepared','committed','accepted')), resource_id TEXT NOT NULL, receipt_json TEXT CHECK(receipt_json IS NULL OR json_valid(receipt_json))) STRICT;
CREATE TABLE global_jobs (id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL, result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json))) STRICT;
