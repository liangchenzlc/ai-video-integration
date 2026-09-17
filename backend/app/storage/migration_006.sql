CREATE TABLE candidate_results (
 call_id TEXT NOT NULL REFERENCES service_calls(id),
 result_ordinal INTEGER NOT NULL CHECK(result_ordinal>=0),
 raw_result_json TEXT NOT NULL CHECK(json_valid(raw_result_json)),
 parse_state TEXT NOT NULL CHECK(parse_state IN ('pending','registered','invalid')),
 result_kind TEXT CHECK(result_kind IN ('text','image')),
 revision_id TEXT UNIQUE REFERENCES revisions(id),
 media_id TEXT REFERENCES media_files(id),
 error_code TEXT CHECK(error_code IS NULL OR length(error_code) BETWEEN 1 AND 100),
 PRIMARY KEY(call_id,result_ordinal),
 CHECK((parse_state='pending' AND revision_id IS NULL AND error_code IS NULL)
    OR (parse_state='registered' AND error_code IS NULL
        AND (revision_id IS NOT NULL OR media_id IS NOT NULL))
    OR (parse_state='invalid' AND revision_id IS NULL AND media_id IS NULL
        AND error_code IS NOT NULL))
) STRICT;
CREATE INDEX candidate_revision_idx ON candidate_results(revision_id);
CREATE INDEX candidate_media_idx ON candidate_results(media_id);
