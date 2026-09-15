"""Generate reviewable design contracts, never a production API or provider client."""
from pathlib import Path
import copy
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '契约'
S = {}

def ref(name):
    return {'$ref': '#/components/schemas/' + name}

def obj(**fields):
    return {'type': 'object', 'additionalProperties': False, 'required': list(fields), 'properties': fields}

def arr(item, maximum=1000, minimum=0):
    return {'type': 'array', 'items': item, 'minItems': minimum, 'maxItems': maximum}

def enum(*values):
    return {'type': 'string', 'enum': list(values)}

def string(maximum=2000, minimum=1):
    return {'type': 'string', 'minLength': minimum, 'maxLength': maximum}

def integer(minimum=0, maximum=9007199254740991):
    return {'type': 'integer', 'minimum': minimum, 'maximum': maximum}

def nullable(schema):
    return {'anyOf': [schema, {'type': 'null'}]}

BOOL = {'type': 'boolean'}
S['Uuid'] = {'type': 'string', 'pattern': '^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'}
S['Hash'] = {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}
S['TimeRange'] = obj(startMs=integer(), endMs=integer(1))
S['Fps'] = obj(numerator={'enum': [24, 25, 30]}, denominator={'const': 1})
S['Stage'] = enum('story', 'image', 'video', 'speech', 'lipsync', 'music', 'sfx', 'check')
S['PipelinePhase'] = enum('story_adaptation', 'story_outline', 'story_scene', 'story_dialogue', 'image_character', 'image_location', 'image_prop', 'image_keyframe', 'video', 'speech', 'lipsync', 'music', 'sfx', 'check')
S['SourceSpan'] = obj(sourceHash=ref('Hash'), startCodePoint=integer(), endCodePoint=integer(1))
S['Requirement'] = obj(id=ref('Uuid'), text=string(), category=enum('fact', 'action', 'dialogue', 'sound', 'screenText', 'reveal'), source=nullable(ref('SourceSpan')), required=BOOL, decision=enum('keep', 'omit', 'replace', 'unresolved'), decisionReason=string(2000, 0))
S['Dialogue'] = obj(id=ref('Uuid'), speakerAssetId=ref('Uuid'), text=string(2000), delivery=enum('visible', 'VO', 'OS'), requirementIds=arr(ref('Uuid')), sceneId=ref('Uuid'))
S['Scene'] = obj(id=ref('Uuid'), title=string(200), action=string(10000), plannedMs=integer(1), locationAssetId=nullable(ref('Uuid')))
S['StoryPayload'] = obj(sourceText=string(100000), sourceHash=ref('Hash'), inputType=enum('idea', 'excerpt', 'script'), approvalLevel=enum('proposal', 'outline', 'scenes', 'dialogue'), brief=string(10000), outline=arr(string(4000), 100), requirements=arr(ref('Requirement')), scenes=arr(ref('Scene'), 200), dialogues=arr(ref('Dialogue')), adaptationNotes=arr(string(4000), 200))
S['Reference'] = obj(mediaId=ref('Uuid'), mediaHash=ref('Hash'), role=enum('identity', 'style', 'location', 'prop', 'composition', 'firstFrame', 'keyMoment', 'endFrame', 'voiceDrive', 'voiceReference'), order=integer(0, 15), state=enum('pending', 'imported', 'verified', 'missing', 'incompatible'), keep=arr(string()), ignore=arr(string()), crop=nullable(obj(x=integer(), y=integer(), width=integer(1), height=integer(1))))
S['PersistentState'] = obj(id=ref('Uuid'), description=string(), reason=string(), fromShotId=ref('Uuid'), throughShotId=ref('Uuid'))
S['AssetPayload'] = obj(assetType=enum('character', 'location', 'prop', 'style'), name=string(200), identityAnchors=arr(string(), 50, 1), allowedChanges=arr(string(), 50), states=arr(ref('PersistentState')), references=arr(ref('Reference'), 16))
S['Event'] = obj(id=ref('Uuid'), text=string(), time=ref('TimeRange'), requirementIds=arr(ref('Uuid')), carrier=enum('visual', 'audio', 'subtitle', 'screenText'), observer=enum('physical', 'character', 'audience'))
S['ShotPayload'] = obj(shotId=ref('Uuid'), purpose=string(), sceneId=ref('Uuid'), assetRevisionIds=arr(ref('Uuid'), 30), requirementIds=arr(ref('Uuid')), startState=string(), events=arr(ref('Event'), 100), endState=string(), camera=string(4000), subjectHand=enum('left', 'right', 'both', 'none'), plannedMs=integer(1), dialogueIds=arr(ref('Uuid'), 50), references=arr(ref('Reference'), 16), videoMediaId=nullable(ref('Uuid')), pickupOfShotId=nullable(ref('Uuid')), use=enum('original', 'supplement', 'alternate'))
S['SpeechPayload'] = obj(dialogueId=ref('Uuid'), text=string(), speakerAssetId=ref('Uuid'), mediaId=ref('Uuid'), measuredMs=integer(1), voicedRanges=arr(ref('TimeRange'), 100), timingMethod=enum('manual', 'provider_sentence', 'provider_word', 'estimated'), voicePreset=string(200), pronunciationNotes=string(2000, 0))
S['Cue'] = obj(id=ref('Uuid'), dialogueId=nullable(ref('Uuid')), text=string(500), time=ref('TimeRange'), differsFromDialogue=BOOL)
S['SubtitlePayload'] = obj(audioRevisionId=nullable(ref('Uuid')), timingMethod=enum('manual', 'provider_sentence', 'provider_word', 'estimated'), cues=arr(ref('Cue'), 2000))
S['Keyframe'] = obj(timeMs=integer(), property=enum('x', 'y', 'scale', 'opacity', 'volume'), value={'type': 'number', 'minimum': -10000, 'maximum': 10000}, interpolation=enum('linear', 'hold'))
S['Clip'] = obj(id=ref('Uuid'), trackId=ref('Uuid'), shotId=nullable(ref('Uuid')), mediaId=nullable(ref('Uuid')), contentRevisionId=nullable(ref('Uuid')), startMs=integer(), inMs=integer(), outMs=integer(1), durationMs=integer(1), gainDb={'type': 'number', 'minimum': -96, 'maximum': 12}, linkedClipIds=arr(ref('Uuid')), keyframes=arr(ref('Keyframe')))
S['Track'] = obj(id=ref('Uuid'), kind=enum('image', 'video', 'voice', 'music', 'sfx', 'subtitle'), order=integer(0, 100), muted=BOOL)
S['Transition'] = obj(id=ref('Uuid'), fromClipId=ref('Uuid'), toClipId=ref('Uuid'), type=enum('cut', 'dissolve', 'fade'), durationMs=integer(0, 10000))
S['TimelinePayload'] = obj(width={'enum': [720, 1080, 1280, 1920]}, height={'enum': [720, 1080, 1280, 1920]}, fps=ref('Fps'), durationMs=integer(1), tracks=arr(ref('Track'), 100, 1), clips=arr(ref('Clip'), 5000), transitions=arr(ref('Transition'), 1000), burnSubtitles=BOOL)
S['ObservationPayload'] = obj(mediaId=ref('Uuid'), mediaHash=ref('Hash'), method=enum('human', 'ai', 'technical'), observed=arr(ref('TimeRange')), usable=arr(ref('TimeRange')), problems=arr(obj(time=ref('TimeRange'), text=string())), limitations=string(4000, 0))
payloads = {'story': 'StoryPayload', 'asset': 'AssetPayload', 'shot': 'ShotPayload', 'speech': 'SpeechPayload', 'subtitle': 'SubtitlePayload', 'timeline': 'TimelinePayload', 'observation': 'ObservationPayload'}
S['TypedPayload'] = {'oneOf': [obj(kind={'const': kind}, content=ref(schema)) for kind, schema in payloads.items()]}
S['Revision'] = obj(id=ref('Uuid'), artifactId=ref('Uuid'), parentId=nullable(ref('Uuid')), payload=ref('TypedPayload'), contentHash=ref('Hash'), createdAt=string(40))
S['Project'] = obj(id=ref('Uuid'), name=string(120), revision=integer(), eventSequence=integer(), formatVersion=integer(1), aspect=enum('16:9', '9:16'), resolution=enum('720p', '1080p'), fps=ref('Fps'), targetMs=integer(1), budgetMicroCny=integer(), savedAt=nullable(string(40)), readOnly=BOOL)
S['Media'] = obj(id=ref('Uuid'), sha256=ref('Hash'), byteLength=integer(1), mime=enum('image/png', 'image/jpeg', 'video/mp4', 'audio/wav', 'audio/mpeg', 'audio/mp4'), durationMs=nullable(integer(1)), width=nullable(integer(1)), height=nullable(integer(1)), availability=enum('staging', 'available', 'missing', 'quarantined'), provenance=enum('imported', 'generated', 'derived', 'synthetic'))
S['Job'] = obj(id=ref('Uuid'), kind=enum('import', 'probe', 'animatic', 'export', 'diagnostic', 'local_check'), state=enum('queued', 'running', 'succeeded', 'failed', 'cancelled'), progress={'type': 'number', 'minimum': 0, 'maximum': 1}, resultId=nullable(ref('Uuid')), errorCode=nullable(string(100)))
S['TaskStep'] = obj(id=ref('Uuid'), purpose=enum('create', 'revise', 'precheck'), capabilityId=ref('Uuid'), maxCalls=integer(1, 16), requestedMs=nullable(integer(1)), maxMicroCny=integer(), disclosure=arr(enum('text', 'image', 'audio', 'video', 'upload')))
S['TaskPlan'] = obj(id=ref('Uuid'), objectId=ref('Uuid'), stage=ref('Stage'), goal=string(), inputRevisionIds=arr(ref('Uuid')), inputMediaHashes=arr(ref('Hash')), steps=arr(ref('TaskStep'), 32, 1), candidates=integer(1, 8), maximumMicroCny=integer(), priceVersion=string(100), templateVersion=string(100), expiresAt=string(40), executionMode=enum('synthetic', 'real'))
S['TaskPlan']['properties']['phase'] = ref('PipelinePhase')
S['TaskPlan']['required'].append('phase')
S['Task'] = obj(id=ref('Uuid'), planId=ref('Uuid'), state=enum('pending', 'running', 'complete', 'partial', 'result_unknown', 'pending_download', 'failed'), eventSequence=integer(), callIds=arr(ref('Uuid')), candidateRevisionIds=arr(ref('Uuid')), observationStopped=BOOL)
S['Call'] = obj(id=ref('Uuid'), taskId=ref('Uuid'), stepId=ref('Uuid'), submissionToken=ref('Uuid'), remoteTaskId=nullable(string(300)), state=enum('prepared', 'submitting', 'running', 'result_unknown', 'pending_download', 'succeeded', 'failed', 'cancelled'), resultMediaIds=arr(ref('Uuid')), billingState=enum('pending', 'settled'), reservedMicroCny=integer(), settledMicroCny=nullable(integer()), expiresAt=nullable(string(40)))
S['CostSummary'] = obj(settledMicroCny=integer(), reservedMicroCny=integer(), remainingWorkMicroCny=integer(), reworkScenarioMicroCny=integer(), forecastMicroCny=integer(), budgetMicroCny=integer(), containsUnknown=BOOL, estimateVersion=string(100))
S['CostEntry'] = obj(callId=ref('Uuid'), state=enum('pending', 'settled'), reservedMicroCny=integer(), settledMicroCny=nullable(integer()), basis=string(2000, 0))
S['Impact'] = obj(previewId=ref('Uuid'), artifactId=ref('Uuid'), fromRevisionId=nullable(ref('Uuid')), toRevisionId=ref('Uuid'), affectedArtifactIds=arr(ref('Uuid')), affectedScopes=arr(enum('identityVisual', 'dialogueAudio', 'subtitleTiming', 'referenceInput', 'requirementCoverage', 'revealTiming', 'timelinePlacement', 'mix', 'export')), estimatedExtraMicroCny=nullable(integer()), requiredChecks=arr(string()), expiresAt=string(40))
S['Issue'] = obj(id=ref('Uuid'), ruleId=string(100), ruleVersion=string(100), artifactId=ref('Uuid'), revisionId=ref('Uuid'), baselineRevisionId=nullable(ref('Uuid')), severity=enum('blocking', 'unknown_required', 'deviation', 'advice'), status=enum('open', 'fixing', 'recheck', 'resolved', 'accepted_deviation'), message=string(), evidence=string(4000, 0), time=nullable(ref('TimeRange')), method=enum('local', 'ai', 'human'), limitations=string(4000, 0))
S['Capability'] = obj(id=ref('Uuid'), providerId=string(100), modelId=string(200), region=string(100), version=string(100), stage=ref('Stage'), accountState=enum('unknown', 'available', 'unavailable'), interfaceState=enum('unverified', 'verified', 'unavailable'), qualityState=enum('unverified', 'research_only', 'verified'), enabled=BOOL, maxReferences=integer(0, 16), supportedReferenceRoles=arr(string(100), 16), durationOptionsMs=arr(integer(1), 100), supportsQuery=BOOL, supportsCancel=BOOL, priceSource=string(2000), priceDate=string(40), restrictions=arr(string()))
for key, schema in {'phases': arr(ref('PipelinePhase'),14,1), 'supportsAudioDrive': BOOL, 'supportsLipsync': BOOL, 'voicePresets': arr(string(200),1000), 'maxInputBytes': nullable(integer(1)), 'maxInputCodePoints': nullable(integer(1)), 'resultLifetimeSeconds': nullable(integer(1)), 'supportsAnonymousResultDownload': BOOL}.items():
    S['Capability']['properties'][key] = schema
    S['Capability']['required'].append(key)
S['Job']['properties']['kind']['enum'].append('connection_check')
S['Settings'] = obj(revision=integer(), providers=arr(obj(providerId=string(100), credentialConfigured=BOOL, maskedSuffix=nullable(string(4, 4)), storageConfigured=BOOL)), ffmpegConfigured=BOOL, capabilities=arr(ref('Capability')))
S['MutationReceipt'] = obj(operationId=ref('Uuid'), committedRevision=integer(), resourceId=ref('Uuid'), state=string(100))
S['Operation'] = obj(operationId=ref('Uuid'), state=enum('committed', 'accepted'), receipt=ref('MutationReceipt'))
S['Session'] = obj(projectId=ref('Uuid'), projectSessionId=ref('Uuid'), mode=enum('read', 'write'), project=ref('Project'))
S['RightEvidence'] = obj(id=ref('Uuid'), mediaId=ref('Uuid'), source=string(), use=string(), evidenceMediaIds=arr(ref('Uuid')), state=enum('unverified', 'verified', 'recheck'), explanation=string(4000, 0))
S['ExportRecord'] = obj(id=ref('Uuid'), timelineRevisionId=ref('Uuid'), jobId=ref('Uuid'), state=enum('pending', 'complete', 'failed', 'cancelled'), mediaId=nullable(ref('Uuid')), inputHash=ref('Hash'))
S['CheckReport'] = obj(id=ref('Uuid'), revisionIds=arr(ref('Uuid'),1000,1), ruleIds=arr(string(100),200,1), outcome=enum('pass','fail','unknown','not_applicable'), issueIds=arr(ref('Uuid')), method=enum('local','ai','human'), observedRanges=arr(ref('TimeRange')), evidenceMediaIds=arr(ref('Uuid')), ruleVersion=string(100), limitations=string(4000,0))
S['AcceptanceRecord'] = obj(id=ref('Uuid'), sampleId=string(40), reviewerId=string(100), evidenceMediaIds=arr(ref('Uuid')), technical=enum('pass', 'fail', 'unknown'), consistency=enum('pass', 'fail', 'unknown'), artistic=enum('pass', 'fail', 'unknown'), sound=enum('pass', 'fail', 'unknown'), notes=string(10000), provenance=enum('human', 'synthetic'))
S['AdoptionSnapshot'] = obj(projectRevision=integer(), artifacts=arr(obj(artifactId=ref('Uuid'), adoptedRevisionId=nullable(ref('Uuid')), confirmedRevisionId=nullable(ref('Uuid')), needsUpdate=BOOL)), shotOrder=arr(ref('Uuid')), requirementBindings=arr(obj(requirementId=ref('Uuid'), shotRevisionIds=arr(ref('Uuid')))), activeTimelineRevisionId=nullable(ref('Uuid')))
S['RenderPlan'] = obj(id=ref('Uuid'), compilerVersion=string(100), timelineRevisionId=ref('Uuid'), timeline=ref('TimelinePayload'), mediaHashes=arr(obj(mediaId=ref('Uuid'), sha256=ref('Hash'))), inputHash=ref('Hash'), videoCodec={'const':'h264'}, audioCodec=nullable({'const':'aac'}), purpose=enum('preview','animatic','export'))
S['CredentialSecret'] = {'oneOf': [obj(kind={'const':'api_key'}, apiKey=string(8192)), obj(kind={'const':'oss'}, accessKeyId=string(256), accessKeySecret=string(8192), securityToken=nullable(string(16384)))]}
S['ErrorResponse'] = obj(requestId=ref('Uuid'), error=obj(code=string(100), message=string(), affectedIds=arr(ref('Uuid')), recoverableAction=enum('none', 'restart_backend', 'retry_connection', 'repair_installation', 'reopen_project', 'review_changes', 'configure', 'review_budget', 'locate_media', 'review_checks', 'query_operation')))

PATHS = {}
ENDPOINTS = []

def endpoint(module, method, path, operation, request=None, response=None, status=200, description=''):
    params = [{'in': 'header', 'name': 'X-Request-Id', 'required': False, 'schema': ref('Uuid')}]
    import re
    for parameter in re.findall(r'\{([^}]+)\}', path):
        params.append({'in': 'path', 'name': parameter, 'required': True, 'schema': string(100) if parameter == 'providerId' else ref('Uuid')})
    if '{projectId}' in path:
        params.append({'in': 'header', 'name': 'X-Project-Session', 'required': True, 'schema': ref('Uuid')})
    body = {'operationId': operation, 'tags': [module], 'summary': description or operation, 'parameters': params, 'responses': {}}
    if request:
        body['requestBody'] = {'required': True, 'content': {'application/json': {'schema': ref(request)}}}
    response = response or 'MutationReceipt'
    response_name = response + 'Response'
    S.setdefault(response_name, obj(requestId=ref('Uuid'), data=ref(response)))
    body['responses'][str(status)] = {'description': '设计成功响应；不证明服务已实现', 'content': {'application/json': {'schema': ref(response_name)}}}
    for code in [400, 401, 403, 404, 409, 413, 422, 500, 503]:
        body['responses'][str(code)] = {'description': '见共用错误与本模块规则', 'content': {'application/json': {'schema': ref('ErrorResponse')}}}
    PATHS.setdefault('/api/v1' + path, {})[method] = body
    ENDPOINTS.append({'module': module, 'method': method.upper(), 'path': '/api/v1' + path, 'operationId': operation, 'request': request, 'response': response, 'status': status})

def command(schema_name, **fields):
    S[schema_name] = obj(clientOperationId=ref('Uuid'), expectedRevision=integer(), payload=obj(**fields))
    return schema_name

def page(name, item):
    S[name] = obj(items=arr(ref(item), 200), nextCursor=nullable(string(500)))
    return name

P = '/projects/{projectId}'
command('RegisterGrant', grantId=ref('Uuid'), path=string(32767), purpose=enum('createProject', 'openProject', 'importMedia', 'exportFile', 'ffmpeg'), windowId=integer(1))
endpoint('T02', 'post', '/file-grants', 'registerFileGrant', 'RegisterGrant', description='仅 main 登记原生文件选择授权')
command('CreateProject', directoryGrantId=ref('Uuid'), name=string(120), aspect=enum('16:9', '9:16'), resolution=enum('720p', '1080p'), fps=ref('Fps'), targetMs=integer(1))
endpoint('T02', 'post', '/projects', 'createProject', 'CreateProject', status=201)
S['OpenProject'] = obj(directoryGrantId=ref('Uuid'), requestedMode=enum('read', 'write'))
endpoint('T02', 'post', '/project-sessions', 'openProject', 'OpenProject', 'Session', 201)
endpoint('T02', 'get', P, 'getProject', response='Project')
endpoint('T02', 'get', '/operations/{operationId}', 'getGlobalOperation', response='Operation')
endpoint('T02', 'get', P + '/operations/{operationId}', 'getProjectOperation', response='Operation')
command('SaveDraft', draftId=ref('Uuid'), artifactId=ref('Uuid'), baseRevisionId=nullable(ref('Uuid')), content=ref('TypedPayload'))
endpoint('T02', 'put', P + '/drafts/{draftId}', 'saveDraft', 'SaveDraft')
S['Draft'] = obj(id=ref('Uuid'), artifactId=ref('Uuid'), baseRevisionId=nullable(ref('Uuid')), content=ref('TypedPayload'))
endpoint('T02', 'get', P + '/drafts/{draftId}', 'getDraft', response='Draft')
command('ImportMedia', fileGrantId=ref('Uuid'), purpose=enum('reference', 'speech', 'video', 'music', 'sfx', 'evidence'))
endpoint('T02', 'post', P + '/imports', 'importMedia', 'ImportMedia', status=202)
endpoint('T02', 'get', P + '/media/{mediaId}/metadata', 'getMediaMetadata', response='Media')
endpoint('T02', 'get', P + '/jobs/{jobId}', 'getLocalJob', response='Job')
command('RelocateMedia', fileGrantId=ref('Uuid'), expectedHash=ref('Hash'))
endpoint('T02', 'post', P + '/media/{mediaId}/relocate', 'relocateMedia', 'RelocateMedia')
command('CancelJob', reason=string(500))
endpoint('T02', 'post', P + '/jobs/{jobId}/cancel', 'cancelLocalJob', 'CancelJob')
# Binary media stream is the sole non-JSON response, still authenticated.
endpoint('T02', 'get', P + '/media/{mediaId}', 'streamMedia', response='Media')
stream = PATHS['/api/v1' + P + '/media/{mediaId}']['get']
stream['parameters'].append({'in': 'header', 'name': 'Range', 'required': False, 'schema': string(200)})
for code in ['200', '206']:
    stream['responses'][code] = {'description': '已授权媒体流，单 Range；正确 MIME/Length/Content-Range', 'content': {'application/octet-stream': {'schema': {'type': 'string', 'format': 'binary'}}}}
stream['responses']['416'] = {'description': 'Range 越界，返回 Content-Range: bytes */length'}
ENDPOINTS[-1]['binary'] = True

endpoint('T03', 'get', '/settings', 'getSettings', response='Settings')
command('SetCredential', secret=ref('CredentialSecret'), persistence=enum('dpapi', 'session_only'))
S['SetCredential']['properties']['payload']['properties']['secret']['writeOnly'] = True
endpoint('T03', 'put', '/credentials/{providerId}', 'setCredential', 'SetCredential')
command('DeleteCredential', confirmed=BOOL)
endpoint('T03', 'post', '/credentials/{providerId}/delete', 'deleteCredential', 'DeleteCredential')
command('ConfigureTools', ffmpegGrantId=ref('Uuid'))
endpoint('T03', 'put', '/settings/media-tools', 'configureMediaTools', 'ConfigureTools')
command('ConfigureStorage', providerId=string(100), region=string(100), bucket=string(100), credentialRef=ref('Uuid'), retentionHours=integer(1, 168))
endpoint('T03', 'put', '/settings/storage', 'configureStorage', 'ConfigureStorage')
command('ConfigureStage', phase=ref('PipelinePhase'), capabilityId=ref('Uuid'))
endpoint('T03', 'put', P + '/stage-models', 'configureStageModel', 'ConfigureStage')
command('ConnectionCheck', capabilityId=ref('Uuid'))
endpoint('T03', 'post', '/connection-checks', 'checkConnection', 'ConnectionCheck', status=202)
endpoint('T03', 'get', '/jobs/{jobId}', 'getGlobalJob', response='Job')

command('PlanTask', objectId=ref('Uuid'), stage=ref('Stage'), phase=ref('PipelinePhase'), goal=string(), inputRevisionIds=arr(ref('Uuid')), candidates=integer(1, 8), includePrecheck=BOOL, executionMode=enum('synthetic', 'real'))
endpoint('T04', 'post', P + '/task-plans', 'planTask', 'PlanTask')
endpoint('T04', 'get', P + '/task-plans/{planId}', 'getTaskPlan', response='TaskPlan')
command('StartTask', planId=ref('Uuid'), authorizedMaximumMicroCny=integer(), disclosureAccepted=BOOL)
endpoint('T04', 'post', P + '/tasks', 'startTask', 'StartTask', status=202)
endpoint('T04', 'get', P + '/tasks/{taskId}', 'getTask', response='Task')
endpoint('T04', 'get', P + '/calls/{callId}', 'getCall', response='Call')
command('RecoverCall', action=enum('query', 'download', 'stop_waiting', 'cancel_remote'))
endpoint('T04', 'post', P + '/calls/{callId}/recovery', 'recoverCall', 'RecoverCall', status=202)
command('ContinueTask', confirmedUnsubmittedOnly=BOOL)
endpoint('T04', 'post', P + '/tasks/{taskId}/continue', 'continuePreparedTask', 'ContinueTask', status=202)
command('SetBudget', totalMicroCny=integer(), allocations=arr(obj(stage=ref('Stage'), limitMicroCny=integer()), 8), warningPercent=integer(1, 100))
endpoint('T04', 'put', P + '/budget', 'setBudget', 'SetBudget')
endpoint('T04', 'get', P + '/cost-summary', 'getCostSummary', response='CostSummary')
endpoint('T04', 'get', P + '/cost-entries', 'listCostEntries', response=page('CostEntryPage', 'CostEntry'))
command('SettleCall', settledMicroCny=integer(), basis=string(), evidenceMediaIds=arr(ref('Uuid')), reason=string())
endpoint('T04', 'post', P + '/calls/{callId}/settlements', 'settleCall', 'SettleCall')
command('ExternalExpense', expenseId=ref('Uuid'), category=enum('storage', 'transfer', 'procurement'), state=enum('estimated', 'pending', 'settled'), amountMicroCny=integer(), basis=string())
endpoint('T04', 'put', P + '/external-expenses/{expenseId}', 'setExternalExpense', 'ExternalExpense')

endpoint('T05', 'get', P + '/artifacts/{artifactId}/revisions', 'listRevisions', response=page('RevisionPage', 'Revision'))
command('CreateRevision', draftId=ref('Uuid'))
endpoint('T05', 'post', P + '/artifacts/{artifactId}/revisions', 'createRevision', 'CreateRevision', status=201)
S['PreviewAdoption'] = obj(toRevisionId=ref('Uuid'), expectedRevision=integer())
endpoint('T05', 'post', P + '/artifacts/{artifactId}/adoption-preview', 'previewAdoption', 'PreviewAdoption', 'Impact')
command('AdoptRevision', previewId=ref('Uuid'), toRevisionId=ref('Uuid'), confirm=BOOL)
endpoint('T05', 'post', P + '/artifacts/{artifactId}/adoptions', 'adoptRevision', 'AdoptRevision')
command('ConfirmRevision', revisionId=ref('Uuid'), checkIds=arr(ref('Uuid')))
endpoint('T05', 'post', P + '/artifacts/{artifactId}/confirmations', 'confirmRevision', 'ConfirmRevision')
command('UndoAdoption', adoptionId=ref('Uuid'))
endpoint('T05', 'post', P + '/adoptions/{adoptionId}/undo', 'undoAdoption', 'UndoAdoption')

endpoint('T06', 'get', P + '/tasks/{taskId}/candidates', 'listCandidates', response=page('CandidatePage', 'Revision'))
command('ReorderShots', shotIds=arr(ref('Uuid'), 5000, 1))
endpoint('T07', 'put', P + '/shot-order', 'reorderShots', 'ReorderShots')
S['Coverage'] = obj(unassignedRequirementIds=arr(ref('Uuid')), unresolvedRequirementIds=arr(ref('Uuid')), invalidReferenceIds=arr(ref('Uuid')))
endpoint('T07', 'get', P + '/coverage', 'getRequirementCoverage', response='Coverage')
command('VerifyReference', draftId=ref('Uuid'), mediaId=ref('Uuid'), role=string(100), matchesPurpose=BOOL, note=string())
endpoint('T07', 'post', P + '/references/verification', 'verifyReference', 'VerifyReference')
S['TimingRequest'] = obj(shotRevisionId=ref('Uuid'), speechRevisionIds=arr(ref('Uuid')), beforeMs=integer(), afterMs=integer())
S['TimingResult'] = obj(requiredMs=integer(), plannedMs=integer(), shortageMs=integer(), method=enum('measured', 'estimated'), suitable=BOOL)
endpoint('T08', 'post', P + '/timing-checks', 'checkTiming', 'TimingRequest', 'TimingResult')
command('RenderAnimatic', timelineRevisionId=ref('Uuid'))
endpoint('T09', 'post', P + '/animatics', 'renderAnimatic', 'RenderAnimatic', status=202)
S['ReplacePreview'] = obj(timelineRevisionId=ref('Uuid'), clipId=ref('Uuid'), newMediaId=ref('Uuid'))
S['ReplaceResult'] = obj(shortageMs=integer(), affectedClipIds=arr(ref('Uuid')), requiredChecks=arr(string()), canPreserveEdit=BOOL)
endpoint('T09', 'post', P + '/timeline/replacement-preview', 'previewMediaReplacement', 'ReplacePreview', 'ReplaceResult')
S['VideoReadiness'] = obj(shotRevisionId=ref('Uuid'), speechRevisionIds=arr(ref('Uuid')), capabilityId=ref('Uuid'), path=enum('research', 'production'))
S['ReadinessResult'] = obj(ready=BOOL, blockers=arr(string()), warnings=arr(string()))
endpoint('T10', 'post', P + '/video-readiness', 'checkVideoReadiness', 'VideoReadiness', 'ReadinessResult')
command('SaveRights', evidence=ref('RightEvidence'))
endpoint('T11', 'put', P + '/rights/{evidenceId}', 'saveRightsEvidence', 'SaveRights')
command('RunLocalChecks', revisionIds=arr(ref('Uuid')), ruleIds=arr(string(100), 200))
endpoint('T12', 'post', P + '/local-checks', 'runLocalChecks', 'RunLocalChecks', status=202)
endpoint('T12', 'get', P + '/check-reports/{checkId}', 'getCheckReport', response='CheckReport')
endpoint('T12', 'get', P + '/issues', 'listIssues', response=page('IssuePage', 'Issue'))
command('DecideIssue', action=enum('accept_deviation', 'request_recheck', 'attach_evidence'), reason=string(), evidenceMediaIds=arr(ref('Uuid')))
endpoint('T12', 'post', P + '/issues/{issueId}/decisions', 'decideIssue', 'DecideIssue')
command('ExportFilm', timelineRevisionId=ref('Uuid'), targetGrantId=ref('Uuid'), burnSubtitles=BOOL, overwriteConfirmed=BOOL)
endpoint('T12', 'post', P + '/exports', 'exportFilm', 'ExportFilm', status=202)
endpoint('T12', 'get', P + '/exports/{exportId}', 'getExport', response='ExportRecord')
command('CreateDiagnostic', includeProject=BOOL, includeContent=BOOL, targetGrantId=ref('Uuid'))
endpoint('T13', 'post', '/diagnostics', 'createDiagnostic', 'CreateDiagnostic', status=202)
# T14 is an offline evaluation record, not an unplanned production administration API.

for path, methods in PATHS.items():
    for method, op in methods.items():
        if method == 'get' and any(op['operationId'].startswith(prefix) for prefix in ['list']):
            op['parameters'] += [{'in': 'query', 'name': 'limit', 'schema': integer(1, 200)}, {'in': 'query', 'name': 'cursor', 'schema': string(500)}]

contract = {'openapi': '3.1.0', 'info': {'title': 'AI Video Integration Business Design', 'version': '0.1.0', 'description': 'Design only; T01 runtime API remains in t01-http.openapi.json. No running service or provider capability is claimed.'}, 'security': [{'RuntimeBearer': []}], 'paths': PATHS, 'components': {'securitySchemes': {'RuntimeBearer': {'type': 'http', 'scheme': 'bearer'}}, 'schemas': S}}

def domain_refs(value):
    if isinstance(value, dict):
        return {k: (v.replace('#/components/schemas/', '#/$defs/') if k == '$ref' else domain_refs(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [domain_refs(v) for v in value]
    return value

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

if __name__ == '__main__':
    write(OUT / 'business.openapi.json', contract)
    write(OUT / 'domain.schema.json', {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'urn:ai-video:domain:0.1.0', '$defs': domain_refs(S)})
    write(OUT / 'endpoint-index.json', ENDPOINTS)
    print(f'Design generated: {len(ENDPOINTS)} operations, {len(S)} schemas.')
