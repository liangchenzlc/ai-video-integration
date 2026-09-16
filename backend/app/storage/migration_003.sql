CREATE TABLE stage_models (
  phase TEXT PRIMARY KEY CHECK(phase IN (
    'story_adaptation','story_outline','story_scene','story_dialogue',
    'image_character','image_location','image_prop','image_keyframe',
    'video','speech','lipsync','music','sfx','check')),
  capability_id TEXT NOT NULL, capability_version TEXT NOT NULL
) STRICT;
