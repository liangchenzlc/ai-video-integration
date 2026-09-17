CREATE TABLE storyboard_shots (
 shot_id TEXT PRIMARY KEY, artifact_id TEXT NOT NULL UNIQUE,
 ordinal INTEGER NOT NULL UNIQUE CHECK(ordinal>=0)
) STRICT;
CREATE TABLE reference_verifications (
 id TEXT PRIMARY KEY, draft_id TEXT NOT NULL REFERENCES drafts(id),
 media_id TEXT NOT NULL REFERENCES media_files(id), media_hash TEXT NOT NULL,
 role TEXT NOT NULL, purpose_hash TEXT NOT NULL CHECK(length(purpose_hash)=64),
 matches_purpose INTEGER NOT NULL CHECK(matches_purpose IN (0,1)),
 note TEXT NOT NULL, verified_at TEXT NOT NULL
) STRICT;
CREATE INDEX verification_draft_idx ON reference_verifications(draft_id,media_id,role);
CREATE TABLE revision_reference_verifications (
 revision_id TEXT NOT NULL REFERENCES revisions(id),
 media_id TEXT NOT NULL REFERENCES media_files(id), role TEXT NOT NULL,
 verification_id TEXT NOT NULL REFERENCES reference_verifications(id),
 PRIMARY KEY(revision_id,media_id,role)
) STRICT;
