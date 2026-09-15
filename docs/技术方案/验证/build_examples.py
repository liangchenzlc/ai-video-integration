"""Build synthetic API shapes and coherent domain examples for design review."""
import copy
import hashlib
import json
from pathlib import Path
from build_contracts import S, ENDPOINTS, OUT, write

def uid(n):
    return f'{n:08x}-0000-4000-8000-{n:012x}'

def sample(schema):
    if '$ref' in schema:
        return sample(S[schema['$ref'].split('/')[-1]])
    if 'const' in schema:
        return schema['const']
    if 'enum' in schema:
        return schema['enum'][0]
    if 'anyOf' in schema:
        return None if any(x.get('type') == 'null' for x in schema['anyOf']) else sample(schema['anyOf'][0])
    if 'oneOf' in schema:
        return sample(schema['oneOf'][0])
    kind = schema.get('type')
    if kind == 'object':
        return {k: sample(v) for k, v in schema['properties'].items() if k in schema.get('required', [])}
    if kind == 'array':
        return [sample(schema['items']) for _ in range(schema.get('minItems', 0))]
    if kind in ('integer', 'number'):
        return max(0, schema.get('minimum', 0))
    if kind == 'boolean':
        return False
    if kind == 'string':
        if schema.get('pattern', '').startswith('^[0-9a-f]{8}'):
            return uid(1)
        if schema.get('pattern') == '^[0-9a-f]{64}$':
            return 'a' * 64
        return '示例' if schema.get('maxLength', 100) >= 2 and schema.get('minLength', 0) <= 2 else 'x' * max(1, schema.get('minLength', 1))
    raise ValueError(schema)

examples = []
for ep in ENDPOINTS:
    entry = dict(ep)
    entry['provenance'] = 'synthetic'
    entry['scope'] = 'transport_shape_only; use domain.examples.json for semantic scenarios'
    if ep['request']:
        entry['requestBody'] = sample(S[ep['request']])
    if not ep.get('binary'):
        entry['responseBody'] = {'requestId': uid(100), 'data': sample(S[ep['response']])}
    examples.append(entry)

source = '阿禾左手将一盏灯放入机械猫背部空槽，松手并撤离。'
source_hash = hashlib.sha256(source.encode('utf-8')).hexdigest()
story = {'sourceText': source, 'sourceHash': source_hash, 'inputType': 'script', 'approvalLevel': 'scenes', 'brief': '七镜头流程夹具；不证明效果。', 'outline': ['发现', '借光', '回应'], 'requirements': [{'id': uid(10), 'text': '左手放灯后松手撤离，灯留在猫背。', 'category': 'action', 'source': {'sourceHash': source_hash, 'startCodePoint': 0, 'endCodePoint': len(source)}, 'required': True, 'decision': 'keep', 'decisionReason': ''}], 'scenes': [{'id': uid(20), 'title': '屋檐下', 'action': '借光', 'plannedMs': 30000, 'locationAssetId': None}], 'dialogues': [], 'adaptationNotes': []}
tracks = [{'id': uid(30), 'kind': 'video', 'order': 0, 'muted': False}]
clips, media = [], []
cursor = 0
for i, length in enumerate([4000, 4000, 4000, 5000, 5000, 4000, 4000]):
    clips.append({'id': uid(100+i), 'trackId': uid(30), 'shotId': uid(200+i), 'mediaId': uid(300+i), 'contentRevisionId': None, 'startMs': cursor, 'inMs': 0, 'outMs': length, 'durationMs': length, 'gainDb': 0, 'linkedClipIds': [], 'keyframes': []})
    media.append({'id': uid(300+i), 'sha256': f'{i+1:064x}', 'byteLength': 1024, 'mime': 'video/mp4', 'durationMs': length, 'width': 720, 'height': 1280, 'availability': 'available', 'provenance': 'synthetic'})
    cursor += length
timeline = {'width': 720, 'height': 1280, 'fps': {'numerator': 24, 'denominator': 1}, 'durationMs': cursor, 'tracks': tracks, 'clips': clips, 'transitions': [], 'burnSubtitles': True}
shot = {'shotId': uid(203), 'purpose': '看清灯从左手转移到猫背', 'sceneId': uid(20), 'assetRevisionIds': [], 'requirementIds': [uid(10)], 'startState': '左手握单个灯，猫背空槽', 'events': [{'id': uid(40), 'text': '靠近、落座、松指、撤离', 'time': {'startMs': 0, 'endMs': 5000}, 'requirementIds': [uid(10)], 'carrier': 'visual', 'observer': 'audience'}], 'endState': '手离开，单个灯留猫背', 'camera': '固定近景，同侧轴线', 'subjectHand': 'left', 'plannedMs': 5000, 'dialogueIds': [], 'references': [], 'videoMediaId': uid(303), 'pickupOfShotId': None, 'use': 'original'}

cases = [
 {'id': 'V04-02', 'module': 'T04', 'kind': 'recovery', 'input': {'callState': 'submitting', 'remoteId': None, 'restart': True}, 'expected': {'state': 'result_unknown', 'submitCountAfterRestart': 0, 'reservedReleased': False}},
 {'id': 'V04-03', 'module': 'T04', 'kind': 'recovery', 'input': {'callState': 'running', 'remoteId': 'synthetic-remote-01', 'restart': True}, 'expected': {'state': 'running', 'submitCountAfterRestart': 0, 'nextAction': 'query_original'}},
 {'id': 'V04-05', 'module': 'T04', 'kind': 'cost', 'input': {'reservedMicroCny': 1200000, 'settlementsMicroCny': [1100000, 1100000], 'remainingWorkMicroCny': 2000000, 'reworkMicroCny': 500000}, 'expected': {'chargedMicroCny': 1100000, 'reservedMicroCny': 0, 'forecastMicroCny': 3600000}},
 {'id': 'V08-01', 'module': 'T08', 'kind': 'timing', 'input': {'speechMs': 5200, 'beforeMs': 600, 'afterMs': 600, 'plannedMs': 6000}, 'expected': {'requiredMs': 6400, 'shortageMs': 400, 'suitable': False}},
 {'id': 'V09-01', 'module': 'T09', 'kind': 'timeline', 'input': {'clipDurationsMs': [4000,4000,4000,5000,5000,4000,4000], 'fps': 24}, 'expected': {'durationMs': 30000, 'frames': 720}},
 {'id': 'V09-02', 'module': 'T09', 'kind': 'replacement', 'input': {'requiredMs': 5000, 'availableMs': 3000}, 'expected': {'shortageMs': 2000, 'canPreserveEdit': False}},
 {'id': 'V12-01', 'module': 'T12', 'kind': 'issue', 'input': {'severity': 'blocking', 'action': 'accept_deviation'}, 'expected': {'accepted': False}},
 {'id': 'V14-01', 'module': 'T14', 'kind': 'novice', 'input': {'participants': 5, 'independentCompletions': 3}, 'expected': {'passed': False}},
]

if __name__ == '__main__':
    write(OUT / 'business.examples.json', {'provenance': 'synthetic', 'examples': examples})
    write(OUT / 'domain.examples.json', {'provenance': 'synthetic', 'description': 'Virtual media IDs/hashes are test data, not physical model outputs.', 'typedExamples': [{'schema': 'StoryPayload', 'value': story}, {'schema': 'ShotPayload', 'value': shot}, {'schema': 'TimelinePayload', 'value': timeline}] + [{'schema': 'Media', 'value': m} for m in media], 'scenarios': cases})
    print(f'Generated {len(examples)} API shapes and {len(cases)} behavioral examples.')
