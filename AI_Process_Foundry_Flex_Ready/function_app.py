"""Flex Consumption: fast HTTP submission/status + Blob-backed timer worker.

No Event Grid, service bus, queue, container host or Video Indexer dependency.
Upload media to raw first; never POST hours of media to an HTTP function.
"""
import json
import logging
import re
import azure.functions as func
from engine.config import Settings
from engine.jobs import TERMINAL, advance_job, create_job
from engine.storage import BlobStore, read_json
from engine.transcription import PendingAuthorization

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)
ID = re.compile(r'^proc-[0-9a-f]{16}$')


def response(value, status=200):
    return func.HttpResponse(json.dumps(value, ensure_ascii=False), status_code=status,
                             mimetype='application/json')


@app.route(route='jobs', methods=['POST'])
def submit(req: func.HttpRequest) -> func.HttpResponse:
    try:
        body = req.get_json()
        state = create_job(BlobStore(), body['video_blob'], body.get('transcript_blob'),
                           settings=Settings.from_env(speaker=body.get('speaker', ''),
                                                      rules=body.get('rules', '')),
                           title=body.get('title'))
        return response({'project_id': state['project_id'], 'status': state['status'],
                         'status_path': '/api/jobs/' + state['project_id']}, 202)
    except PendingAuthorization as exc:
        return response({'status': 'pending_authorization', 'message': str(exc)}, 409)
    except (KeyError, ValueError, FileNotFoundError):
        return response({'error': 'Solicitud/configuración inválida o archivo ausente en raw'}, 400)


@app.route(route='jobs/{job_id}', methods=['GET'])
def status(req: func.HttpRequest) -> func.HttpResponse:
    job_id = req.route_params.get('job_id', '')
    if not ID.fullmatch(job_id):
        return response({'error': 'ID inválido'}, 400)
    store = BlobStore()
    if not store.exists('analysis', f'{job_id}/job.json'):
        return response({'error': 'Trabajo no encontrado'}, 404)
    state = read_json(store, 'analysis', f'{job_id}/job.json')
    return response(state)


@app.route(route='jobs/{job_id}/retry', methods=['POST'])
def retry(req: func.HttpRequest) -> func.HttpResponse:
    job_id = req.route_params.get('job_id', '')
    if not ID.fullmatch(job_id):
        return response({'error': 'ID inválido'}, 400)
    store = BlobStore()
    name = f'{job_id}/job.json'
    if not store.exists('analysis', name):
        return response({'error': 'Trabajo no encontrado'}, 404)
    with store.claim(name) as lease:
        if lease is None:
            return response({'status': 'busy'}, 409)
        state = read_json(store, 'analysis', name)
        if state['status'] not in ('failed', 'pending_authorization'):
            return response({'error': 'Solo se reintentan trabajos fallidos o pendientes'}, 409)
        state['status'] = 'queued'
        from engine.storage import json_bytes
        store.put('analysis', name, json_bytes(state), lease=lease)
    return response({'project_id': job_id, 'status': 'queued'}, 202)


@app.timer_trigger(schedule='%PIPELINE_POLL_SCHEDULE%', arg_name='timer',
                   run_on_startup=False, use_monitor=True)
def process_jobs(timer: func.TimerRequest) -> None:
    store = BlobStore()
    # One unit/job/tick. Checkpoints survive restarts; leases exclude duplicate workers.
    jobs = [read_json(store, 'analysis', name) for name in store.list_jobs()]
    for state in sorted(jobs, key=lambda row: row['updated_at']):
        if state['status'] in TERMINAL | {'failed', 'pending_authorization'}:
            continue
        result = advance_job(store, state['project_id'])
        logging.info('Pipeline job %s: %s', state['project_id'], result['status'])
        # Keep invocation bounded and give other jobs priority next tick.
        break
