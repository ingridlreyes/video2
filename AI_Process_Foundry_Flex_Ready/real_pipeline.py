"""Public local API backed by the same resumable engine used in Azure Functions."""
from pathlib import Path
import os
import uuid
from engine.config import ROOT, Settings
from engine.jobs import TERMINAL, advance_job, create_job
from engine.storage import BlobStore, LocalStore, read_json
from engine.vision import azure_client, infer_steps, parse_model_json, related_text


def run_pipeline(video_file, transcript_file=None, main_speaker='', custom_rules='', use_ai=True,
                 limit_minutes=None, max_frames=None, *, resume=None, segment_seconds=None,
                 frame_every_seconds=None):
    """Process the full timeline. Legacy global truncation flags are rejected explicitly."""
    if limit_minutes is not None or max_frames is not None:
        raise ValueError('Se eliminaron limit_minutes/max_frames globales. Usa segment_seconds/frame_every_seconds: no se recorta el video.')
    store = BlobStore() if os.getenv('USE_AZURE_BLOB', 'false').lower() == 'true' else LocalStore(
        os.getenv('PIPELINE_DATA_DIR', str(ROOT / 'runs')))
    if resume:
        job_id = resume
    else:
        video = Path(video_file).resolve()
        if not video.is_file():
            raise FileNotFoundError(video)
        changes = dict(speaker=main_speaker, rules=custom_rules, use_ai=use_ai)
        if segment_seconds is not None:
            changes['segment_seconds'] = segment_seconds
        if frame_every_seconds is not None:
            changes['frame_every_seconds'] = frame_every_seconds
        settings = Settings.from_env(**changes)
        job_id = 'proc-' + uuid.uuid4().hex[:16]
        video_name = f'{job_id}/{video.name}'
        store.upload('raw', video_name, video)
        transcript_name = None
        if transcript_file:
            transcript = Path(transcript_file).resolve()
            transcript_name = f'{job_id}/transcript{transcript.suffix.lower()}'
            store.upload('raw', transcript_name, transcript)
        create_job(store, video_name, transcript_name, settings=settings, title=video.stem, job_id=job_id)
    # Explicit resume retries a failed unit once; no automatic endless paid retry loop.
    state = advance_job(store, job_id, retry=bool(resume))
    while state['status'] not in TERMINAL | {'failed', 'pending_authorization', 'busy'}:
        state = advance_job(store, job_id)
    local = isinstance(store, LocalStore)
    manifest_name = f'{job_id}/procedure.json'
    deliveries = state.get('deliveries', [])
    def location(stage, name):
        return str(store.path(stage, name)) if local else f'{stage}/{name}'
    return {**state, 'manifest': location('analysis', manifest_name) if store.exists('analysis', manifest_name) else None,
            'job': location('analysis', f'{job_id}/job.json'),
            'pptx': location('delivery', deliveries[0]['pptx']) if deliveries else None,
            'docx': location('delivery', deliveries[0]['docx']) if deliveries else None,
            'files': [{kind: location('delivery', row[kind]) for kind in ('pptx', 'docx')} for row in deliveries],
            'steps': state.get('steps', 0), 'frames': state.get('frames', 0)}
