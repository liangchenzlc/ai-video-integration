"""Validate design contracts and examples. This does not test an application."""
from pathlib import Path
import copy
import hashlib
import json
import re
import sqlite3
import sys
from urllib.parse import unquote
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
TECH = ROOT / '技术方案'
CONTRACTS = TECH / '契约'
results = []

def record(name, fn):
    try:
        detail = fn()
        results.append({'name': name, 'passed': True, 'detail': detail})
        print('PASS ' + name + (': ' + str(detail) if detail else ''))
    except Exception as error:
        results.append({'name': name, 'passed': False, 'detail': str(error)})
        print('FAIL ' + name + ': ' + str(error))

def load(name):
    return json.loads((CONTRACTS / name).read_text(encoding='utf-8'))

domain = load('domain.schema.json')
api = load('business.openapi.json')
examples = load('business.examples.json')['examples']
fixtures = load('domain.examples.json')

def validator(name):
    return Draft202012Validator({'$defs': domain['$defs'], '$ref': '#/$defs/' + name})

def contracts():
    Draft202012Validator.check_schema(domain)
    operation_ids = set()
    refs = []
    def walk(value):
        if isinstance(value, dict):
            if '$ref' in value:
                refs.append(value['$ref'])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(api)
    for reference in refs:
        assert reference.startswith('#/components/schemas/'), reference
        assert reference.rsplit('/', 1)[-1] in api['components']['schemas'], reference
    for path, methods in api['paths'].items():
        for method, op in methods.items():
            assert op['operationId'] not in operation_ids
            operation_ids.add(op['operationId'])
            expected = set(re.findall(r'\{([^}]+)\}', path))
            actual = {p['name'] for p in op['parameters'] if p['in'] == 'path' and p['required']}
            assert expected == actual, path
            if '{projectId}' in path:
                assert any(p['name'] == 'X-Project-Session' and p['required'] for p in op['parameters'])
            assert any(code.startswith('2') for code in op['responses'])
    assert operation_ids == {e['operationId'] for e in examples}
    return f'{len(operation_ids)} operations; {len(api["components"]["schemas"])} schemas; all refs resolve'

def transport_examples():
    positives = negatives = 0
    for example in examples:
        name = example['request']
        if name:
            value = example['requestBody']
            validator(name).validate(value)
            positives += 1
            extra = dict(value, undeclaredField=True)
            assert not validator(name).is_valid(extra), name
            negatives += 1
            missing = dict(value)
            missing.pop(next(iter(value)))
            assert not validator(name).is_valid(missing), name
            negatives += 1
        if not example.get('binary'):
            validator(example['response'] + 'Response').validate(example['responseBody'])
            positives += 1
    for value in [True, '1', -1, 1.5]:
        candidate = copy.deepcopy(next(e['requestBody'] for e in examples if e['request'] == 'StartTask'))
        candidate['expectedRevision'] = value
        assert not validator('StartTask').is_valid(candidate)
        negatives += 1
    return f'{positives} positive shapes; {negatives} rejected negative shapes'

def semantics(schema, value, media_by_id=None):
    errors = []
    if schema == 'StoryPayload':
        text = value['sourceText']
        hashed = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if hashed != value['sourceHash']:
            errors.append('SOURCE_HASH_MISMATCH')
        for req in value['requirements']:
            span = req['source']
            if span and not (span['sourceHash'] == hashed and 0 <= span['startCodePoint'] < span['endCodePoint'] <= len(text)):
                errors.append('SOURCE_SPAN_INVALID')
    elif schema == 'ShotPayload':
        for event in value['events']:
            if not (0 <= event['time']['startMs'] < event['time']['endMs'] <= value['plannedMs']):
                errors.append('EVENT_OUT_OF_BOUNDS')
            if not set(event['requirementIds']).issubset(value['requirementIds']):
                errors.append('REQUIREMENT_UNBOUND')
    elif schema == 'TimelinePayload':
        if (value['width'], value['height']) not in [(1280,720), (1920,1080), (720,1280), (1080,1920)]:
            errors.append('CANVAS_INVALID')
        track_ids = {t['id'] for t in value['tracks']}
        clip_ids = {c['id'] for c in value['clips']}
        if len(clip_ids) != len(value['clips']) or len(track_ids) != len(value['tracks']):
            errors.append('DUPLICATE_ID')
        for clip in value['clips']:
            if clip['trackId'] not in track_ids:
                errors.append('TRACK_MISSING')
            if not (clip['inMs'] < clip['outMs'] and clip['startMs'] + clip['durationMs'] <= value['durationMs']):
                errors.append('CLIP_OUT_OF_BOUNDS')
            if media_by_id is not None and clip['mediaId']:
                media = media_by_id.get(clip['mediaId'])
                if media is None:
                    errors.append('MEDIA_MISSING')
                elif media['durationMs'] is not None and (clip['outMs'] > media['durationMs'] or clip['durationMs'] != clip['outMs']-clip['inMs']):
                    errors.append('MEDIA_TOO_SHORT_OR_RETIMED')
            if not set(clip['linkedClipIds']).issubset(clip_ids):
                errors.append('LINKED_CLIP_MISSING')
    return errors

def semantic_examples():
    media = {x['value']['id']: x['value'] for x in fixtures['typedExamples'] if x['schema'] == 'Media'}
    for item in fixtures['typedExamples']:
        validator(item['schema']).validate(item['value'])
        assert not semantics(item['schema'], item['value'], media), item['schema']
    story = copy.deepcopy(fixtures['typedExamples'][0]['value'])
    story['sourceText'] = story['sourceText'].replace('阿禾', '小禾')
    assert 'SOURCE_HASH_MISMATCH' in semantics('StoryPayload', story)
    timeline = copy.deepcopy(fixtures['typedExamples'][2]['value'])
    short = copy.deepcopy(media)
    short[timeline['clips'][3]['mediaId']]['durationMs'] = 3000
    assert 'MEDIA_TOO_SHORT_OR_RETIMED' in semantics('TimelinePayload', timeline, short)
    bad = copy.deepcopy(timeline)
    bad['clips'][0]['trackId'] = 'missing'
    assert 'TRACK_MISSING' in semantics('TimelinePayload', bad, media)
    for case in fixtures['scenarios']:
        source, expected, kind = case['input'], case['expected'], case['kind']
        if kind == 'timing':
            required = source['speechMs'] + source['beforeMs'] + source['afterMs']
            actual = {'requiredMs': required, 'shortageMs': max(0, required-source['plannedMs']), 'suitable': required <= source['plannedMs']}
        elif kind == 'replacement':
            actual = {'shortageMs': max(0, source['requiredMs']-source['availableMs']), 'canPreserveEdit': source['availableMs'] >= source['requiredMs']}
        elif kind == 'timeline':
            duration = sum(source['clipDurationsMs'])
            actual = {'durationMs': duration, 'frames': (duration*source['fps']+500)//1000}
        elif kind == 'cost':
            charged = source['settlementsMicroCny'][-1]
            actual = {'chargedMicroCny': charged, 'reservedMicroCny': 0, 'forecastMicroCny': charged+source['remainingWorkMicroCny']+source['reworkMicroCny']}
        elif kind == 'recovery':
            actual = {'state': 'running' if source['remoteId'] else 'result_unknown', 'submitCountAfterRestart': 0}
            actual.update({'nextAction': 'query_original'} if source['remoteId'] else {'reservedReleased': False})
        elif kind == 'issue':
            actual = {'accepted': source['severity'] in ['deviation', 'advice']}
        elif kind == 'novice':
            actual = {'passed': source['participants'] >= 5 and source['independentCompletions'] >= 4}
        else:
            raise AssertionError(kind)
        assert actual == expected, case['id']
    return f'{len(fixtures["typedExamples"])} typed examples; 3 semantic counterexamples; {len(fixtures["scenarios"])} design oracles (not runtime tests)'

def database():
    db = sqlite3.connect(':memory:')
    db.executescript((TECH/'数据模型/project.sql').read_text(encoding='utf-8'))
    count = db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    db.execute("INSERT INTO projects(id,name,format_version,aspect,resolution,fps_n,target_ms,budget_micro_cny) VALUES('p','测试',1,'9:16','720p',24,30000,10000000)")
    db.execute("INSERT INTO stage_budgets VALUES('video',3000000)")
    db.execute("INSERT INTO task_plans VALUES('plan','object','video','{}',?,1200000,'2099-01-01','synthetic')", ('a'*64,))
    db.execute("INSERT INTO user_tasks(id,plan_id,state,active,authorized_maximum_micro_cny) VALUES('task','plan','running',1,1200000)")
    db.execute("INSERT INTO planned_steps VALUES('step','plan',0,'create',1,1200000,'{}')")
    db.execute("INSERT INTO service_calls(id,task_id,step_id,ordinal,submission_token,provider_id,model_id,region,state,request_hash,request_snapshot_json) VALUES('call','task','step',0,'token','fake','fake','local','result_unknown',?,'{}')", ('a'*64,))
    db.execute("INSERT INTO cost_entries VALUES('call','pending',1200000,NULL,'')")
    assert db.execute('SELECT sum(amount_micro_cny) FROM charged_costs').fetchone()[0] == 1200000
    db.execute("UPDATE cost_entries SET state='settled',settled_micro_cny=1100000,basis='synthetic invoice' WHERE call_id='call'")
    db.execute("UPDATE cost_entries SET settled_micro_cny=1100000 WHERE call_id='call'")
    assert db.execute('SELECT sum(amount_micro_cny) FROM charged_costs').fetchone()[0] == 1100000
    db.execute("INSERT INTO artifacts(id,kind) VALUES('a','story')")
    db.execute("INSERT INTO artifacts(id,kind) VALUES('b','story')")
    db.execute("INSERT INTO revisions VALUES('ra','a',NULL,'{}',?,'2026-09-15')", ('a'*64,))
    db.execute("INSERT INTO revisions VALUES('rb','b',NULL,'{}',?,'2026-09-15')", ('b'*64,))
    db.execute("UPDATE artifacts SET adopted_revision_id='ra',confirmed_revision_id='ra' WHERE id='a'")
    db.commit()
    checks = 0
    def reject(sql, params=()):
        nonlocal checks
        db.execute('BEGIN')
        try:
            db.execute(sql, params)
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            checks += 1
        else:
            raise AssertionError('SQL unexpectedly accepted: ' + sql)
    reject("UPDATE artifacts SET adopted_revision_id='rb' WHERE id='a'")
    reject("UPDATE revisions SET payload_json='[]' WHERE id='ra'")
    reject("INSERT INTO cost_entries VALUES('call','settled',1200000,1100000,'duplicate')")
    reject("INSERT INTO cost_entries VALUES('missing','pending',1,NULL,'')")
    reject("UPDATE cost_entries SET settled_micro_cny=-1 WHERE call_id='call'")
    db.execute("INSERT INTO check_runs VALUES('report','{}','fail','2026-09-15')")
    db.commit()
    reject("INSERT INTO checks VALUES('c','a','ra',NULL,'media.available','v1','local','blocking','accepted_deviation','{}','report')")
    reject("INSERT INTO media_files(id,relative_path,sha256,byte_length,mime,availability,provenance,source_json) VALUES('m','../outside',?,10,'image/png','available','synthetic','{}')", ('a'*64,))
    reject("INSERT INTO revisions VALUES('rc','a','rb','{}',?,'2026-09-15')", ('c'*64,))
    db.execute("INSERT INTO task_plans VALUES('plan2','obj2','video','{}',?,1,'2099','synthetic')", ('b'*64,))
    db.commit()
    reject("INSERT INTO user_tasks(id,plan_id,state,active,authorized_maximum_micro_cny) VALUES('task2','plan2','running',1,1)")
    db.execute("INSERT INTO call_events VALUES(1,'call',1,'submitted','{}','2026-09-15')")
    db.commit()
    reject("DELETE FROM call_events WHERE id=1")
    assert not db.execute('PRAGMA foreign_key_check').fetchall()
    assert db.execute("SELECT adopted_revision_id FROM artifacts WHERE id='a'").fetchone()[0] == 'ra'
    app = sqlite3.connect(':memory:')
    app.executescript((TECH/'数据模型/application.sql').read_text(encoding='utf-8'))
    app.close()
    db.close()
    return f'{count} project tables; application schema executable; {checks} rejected integrity violations; settlement counted once'

def links_and_coverage():
    missing = []
    historical = []
    for doc in ROOT.rglob('*.md'):
        for raw in re.findall(r'\]\((<[^>]+>|[^\s)]+)\)', doc.read_text(encoding='utf-8')):
            target = raw.strip('<>').split('#', 1)[0]
            if not target or re.match(r'^[a-z]+://', target):
                continue
            resolved = (doc.parent/unquote(target)).resolve()
            if not resolved.exists():
                if doc.name == '06-验证记录与参考依据.md' and target.startswith('../.local/'):
                    historical.append(target)
                else:
                    missing.append(f'{doc.name}: {target}')
    assert not missing, '\n'.join(missing)
    assert len(historical) == 10, f'historical missing link count changed: {len(historical)}'
    for module in range(1, 15):
        assert list((TECH/'模块设计').glob(f'T{module:02d}-*.md')), module
    return 'T01–T14 covered; no new broken links; 10 explicitly documented historical gaps'

def t01_contract():
    spec = load('t01-http.openapi.json')
    examples = load('t01-http.examples.json')
    schemas = spec['components']['schemas']
    for key, name in [('health','HealthResponse'), ('capabilities','CapabilitiesResponse'), ('error','ErrorResponse')]:
        Draft202012Validator({'components': {'schemas': schemas}, '$ref': '#/components/schemas/'+name}).validate(examples[key])
    return 'existing T01 health/capabilities/error examples still satisfy design schema'

if __name__ == '__main__':
    for name, fn in [('contracts', contracts), ('transport_examples', transport_examples), ('domain_semantics', semantic_examples), ('sqlite_constraints', database), ('t01_compatibility', t01_contract), ('links_and_module_coverage', links_and_coverage)]:
        record(name, fn)
    output = {'scope': 'design validation only, no product runtime or real provider tested', 'python': sys.version.split()[0], 'sqlite': sqlite3.sqlite_version, 'passed': all(r['passed'] for r in results), 'results': results}
    (ROOT/'开发准备/design-validation.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    sys.exit(0 if output['passed'] else 1)
