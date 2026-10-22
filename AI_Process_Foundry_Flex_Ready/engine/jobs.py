"""One resumable unit per invocation, shared by local CLI and Flex timer workers."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import uuid
from .config import Settings
from .media import duration, extract_audio, extract_frames, plan_segments
from .storage import json_bytes, read_json
from .transcription import MaiTranscriber, PendingAuthorization, check_mai_authorization
from .vision import azure_client, infer_steps, verify_capabilities
from transcript_ingestion import read_transcript

TERMINAL = {'generated_pending_review', 'needs_review', 'extracted_without_ai'}


def now():
    return datetime.now(timezone.utc).isoformat()


def create_job(store, video_blob, transcript_blob=None, *, settings=None, title=None, job_id=None):
    settings = settings or Settings.from_env()
    if not store.exists('raw', video_blob):
        raise FileNotFoundError('Video no encontrado en raw')
    if transcript_blob and not store.exists('raw', transcript_blob):
        raise FileNotFoundError('Transcripción no encontrada en raw')
    if not transcript_blob and settings.transcription_provider == 'supplied' and settings.use_ai:
        raise PendingAuthorization('Proporciona VTT/SRT/JSON; MAI sigue pendiente de autorización')
    if not transcript_blob and settings.transcription_provider == 'mai':
        check_mai_authorization()
    job_id = job_id or 'proc-' + uuid.uuid4().hex[:16]
    state = {'version': 2, 'project_id': job_id, 'title': title or Path(video_blob).stem,
             'video_blob': video_blob, 'transcript_blob': transcript_blob,
             'settings': settings.as_dict(), 'status': 'queued', 'created_at': now(),
             'updated_at': now(), 'next_segment': 0, 'next_volume': 0, 'deliveries': [],
             'attempts': 0, 'capabilities': None}
    store.put('analysis', f'{job_id}/job.json', json_bytes(state), overwrite=False)
    return state


def _supplied_transcript(store, state, temporary):
    name = state['transcript_blob']
    if not name:
        return []
    path = store.materialize('raw', name, temporary / ('transcript' + Path(name).suffix))
    rows = read_transcript(path)
    total = state['duration_seconds']
    if any(s['start'] < 0 or s['end'] > total + 1 for s in rows):
        raise ValueError('Transcripción fuera de la duración del video; alinear antes de analizar')
    return rows


def _process_segment(store, state, settings, temporary, client):
    segment = state['segments'][state['next_segment']]
    sid = f"segment_{segment['index']:06d}"
    prefix = f"{state['project_id']}/{sid}"
    result_name, draft_name = prefix + '/result.json', prefix + '/draft.json'
    if store.exists('analysis', result_name):
        # The unit committed before a host interruption during job-state upload.
        state['next_segment'] += 1
        state['status'] = 'analyzing' if state['next_segment'] < len(state['segments']) else 'exporting'
        return
    if not store.exists('analysis', draft_name):
        source = store.media_source(state['video_blob'])
        rows = _supplied_transcript(store, state, temporary)
        if not state['transcript_blob'] and settings.transcription_provider == 'mai':
            if settings.speaker:
                raise ValueError('Los IDs MAI son locales al segmento; usa transcripción con IDs globales para filtrar instructor')
            audio = temporary / 'audio.mp3'
            extract_audio(source, segment, audio)
            response_file = temporary / 'mai_response.json'
            rows = MaiTranscriber().transcribe(audio, segment['start'], segment['end'] - segment['start'],
                                               sid, response_file)
            store.upload('analysis', prefix + '/mai_response.json', response_file)
        if settings.speaker and (not rows or settings.speaker not in {str(s.get('speaker')) for s in rows}):
            raise ValueError('Instructor ausente de la transcripción; no se excluirá contenido silenciosamente')
        frames = extract_frames(source, segment, temporary / 'frames', settings.frame_every_seconds)
        for frame in frames:
            name = prefix + '/' + Path(frame['image']).name
            store.upload('analysis', name, frame['image'])
            frame['image'] = name
        relevant = [s for s in rows if s['end'] >= segment['start'] and s['start'] < segment['end']]
        draft = {'segment': segment, 'frames': frames, 'transcript': relevant, 'steps': [],
                 'next_frame': 0, 'ai_invoked': settings.use_ai}
        store.put('analysis', draft_name, json_bytes(draft))
        # Media preparation is independent of paid inference and has its own checkpoint.
        if settings.use_ai:
            return
    draft = read_json(store, 'analysis', draft_name)
    if settings.use_ai:
        offset = draft['next_frame']
        batch = [dict(f) for f in draft['frames'][offset:offset + settings.batch_size]]
        mapping = {}
        for frame in batch:
            stored = frame['image']
            frame['image'] = str(store.materialize('analysis', stored, temporary / Path(stored).name))
            mapping[frame['image']] = stored
        steps = infer_steps(client, settings.deployment, batch, draft['transcript'], settings.speaker,
                            settings.rules, settings.batch_size)
        for row in steps:
            row['image'] = mapping[row['image']]
            row['segment_index'] = segment['index']
        draft['steps'].extend(steps)
        draft['next_frame'] += len(batch)
        store.put('analysis', draft_name, json_bytes(draft))
        if draft['next_frame'] < len(draft['frames']):
            return
    draft['completed_at'] = now()
    store.put('analysis', result_name, json_bytes(draft))
    state['next_segment'] += 1
    state['status'] = 'analyzing' if state['next_segment'] < len(state['segments']) else 'exporting'


def _assemble_manifest(store, state):
    steps, coverage = [], []
    frame_count = 0
    for segment in state['segments']:
        result = read_json(store, 'analysis',
                           f"{state['project_id']}/segment_{segment['index']:06d}/result.json")
        coverage.append({**segment, 'frames': len(result['frames']), 'steps': len(result['steps']),
                         'ai_invoked': result['ai_invoked']})
        frame_count += len(result['frames'])
        steps.extend(result['steps'])
    for i, row in enumerate(steps, 1):
        row['id'] = f's{i:06d}'
    settings = state['settings']
    return {'project_id': state['project_id'], 'title': state['title'], 'source_type': 'actual_video',
            'video_blob': state['video_blob'], 'video_duration_seconds': state['duration_seconds'],
            'processed_seconds': sum(s['end'] - s['start'] for s in coverage), 'coverage': coverage,
            'sampling_interval_seconds': settings['frame_every_seconds'], 'frame_candidates': frame_count,
            'capabilities': state['capabilities'], 'rules_summary': settings['rules'],
            'rules': [settings['rules']] if settings['rules'] else [], 'steps': steps,
            'warning': 'Capturas muestreadas: acciones más rápidas que el intervalo pueden no ser visibles.'}


def _export_unit(store, state, temporary):
    from poc_core import generate
    manifest = _assemble_manifest(store, state)
    store.put('analysis', f"{state['project_id']}/procedure.json", json_bytes(manifest))
    state['frames'] = manifest['frame_candidates']
    state['steps'] = len(manifest['steps'])
    if not manifest['steps']:
        state['status'] = 'needs_review' if state['settings']['use_ai'] else 'extracted_without_ai'
        return
    size = int(os.getenv('DOCUMENT_STEPS_PER_VOLUME', '40'))
    if not 1 <= size <= 100:
        raise ValueError('DOCUMENT_STEPS_PER_VOLUME debe estar entre 1 y 100')
    # Persist the chosen volume size: changing environment cannot skip document pages on resume.
    size = state.setdefault('document_steps_per_volume', size)
    start = state['next_volume'] * size
    volume_steps = [dict(s) for s in manifest['steps'][start:start + size]]
    for row in volume_steps:
        row['image'] = str(store.materialize('analysis', row['image'], temporary / 'evidence' / row['image']))
    volume = {**manifest, 'steps': volume_steps,
              'title': f"{state['title']} · Parte {state['next_volume'] + 1}", 'step_offset': start,
              'total_steps': len(manifest['steps'])}
    suffix = f"{state['project_id']}_{state['next_volume'] + 1:04d}"
    pptx, docx = generate(volume, suffix=suffix, output_dir=temporary / 'documents')
    delivered = {}
    for kind, path in (('pptx', pptx), ('docx', docx)):
        name = f"{state['project_id']}/{Path(path).name}"
        store.upload('delivery', name, path)
        delivered[kind] = name
    delivered.update(first_step=start + 1, last_step=start + len(volume_steps))
    state['deliveries'].append(delivered)
    state['next_volume'] += 1
    if state['next_volume'] * size >= len(manifest['steps']):
        state['status'] = 'generated_pending_review'
        store.put('delivery', f"{state['project_id']}/index.json", json_bytes({
            'project_id': state['project_id'], 'steps': state['steps'], 'volumes': state['deliveries'],
            'manifest': f"analysis/{state['project_id']}/procedure.json"}))


def advance_job(store, job_id, *, retry=False):
    """Advance one probe/planning, temporal segment or document volume; atomic state checkpoint."""
    name = f'{job_id}/job.json'
    with store.claim(name) as lease:
        if lease is None:
            return {'project_id': job_id, 'status': 'busy'}
        state = read_json(store, 'analysis', name)
        if state['status'] in TERMINAL:
            return state
        if state['status'] in ('failed', 'pending_authorization') and not retry:
            return state
        state['attempts'] += 1
        try:
            settings = Settings(**state['settings'])
            if settings.use_ai and (settings.deployment != os.getenv('AZURE_VISION_DEPLOYMENT', '') or
                                    settings.api_base_url != os.getenv('AZURE_OPENAI_BASE_URL', '')):
                raise ValueError('Endpoint/deployment cambió; crea un trabajo nuevo para mantener trazabilidad')
            with tempfile.TemporaryDirectory(prefix='process-video-') as folder:
                temporary = Path(folder)
                client = azure_client() if settings.use_ai else None
                if not state.get('segments'):
                    total = duration(store.media_source(state['video_blob']))
                    state['duration_seconds'] = total
                    state['segments'] = plan_segments(total, settings.segment_seconds)
                    _supplied_transcript(store, state, temporary)  # Fail before paid requests if invalid.
                    state['status'] = 'analyzing'
                if settings.use_ai and not state['capabilities']:
                    state['capabilities'] = verify_capabilities(client, settings.deployment)
                    # Probe is its own durable unit, before any analysis requests.
                elif state['next_segment'] < len(state['segments']):
                    _process_segment(store, state, settings, temporary, client)
                else:
                    _export_unit(store, state, temporary)
                state.pop('error', None)
        except PendingAuthorization as exc:
            state.update(status='pending_authorization', error=str(exc))
        except Exception as exc:
            # No SDK exception text: it may include source text, keys or signed media URLs.
            state.update(status='failed', error={'type': type(exc).__name__,
                         'message': str(exc) if isinstance(exc, (ValueError, RuntimeError)) and
                         not type(exc).__module__.startswith(('openai', 'azure', 'requests'))
                         else 'Falló la integración; consultar diagnóstico sin secretos y reintentar'})
        state['updated_at'] = now()
        store.put('analysis', name, json_bytes(state), lease=lease if lease is not True else None)
        return state
