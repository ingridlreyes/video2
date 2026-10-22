"""Vendor-neutral transcript adapter. MAI remains authorization-gated by default."""
import json
import math
import os
from pathlib import Path
import requests
from .config import https_endpoint


class PendingAuthorization(RuntimeError):
    pass


def check_mai_authorization():
    if os.getenv('MAI_AUTHORIZED', 'false').lower() != 'true':
        raise PendingAuthorization('MAI-Transcribe-2 pendiente de revisión y autorización; proporciona VTT/SRT/JSON')
    if not os.getenv('MAI_ENDPOINT'):
        raise PendingAuthorization('Falta MAI_ENDPOINT del recurso autorizado existente')


def normalize_mai(data, offset, length, segment_id):
    """Wire fields from the official Speech REST contract; never fabricate missing timings."""
    if not isinstance(data, dict) or not isinstance(data.get('phrases'), list):
        raise ValueError('Contrato MAI inesperado: falta phrases; conservar respuesta para revisión')
    result = []
    for phrase in data['phrases']:
        text = phrase.get('text', '').strip()
        if not text:
            continue
        start = float(phrase['offsetMilliseconds']) / 1000
        end = start + float(phrase['durationMilliseconds']) / 1000
        if not all(math.isfinite(x) for x in (start, end)) or start < 0 or end < start or end > length + 1:
            raise ValueError('Tiempos MAI fuera del segmento')
        speaker = phrase.get('speaker')
        # MAI speaker IDs are local to the request, not globally verified identities.
        result.append({'start': offset + start, 'end': offset + end, 'text': text,
                       'speaker': f'{segment_id}:{speaker}' if speaker is not None else None,
                       'source': 'mai_transcribe_2', 'speaker_scope': segment_id})
    if not result and any(p.get('text', '').strip() for p in data.get('combinedPhrases', [])):
        raise ValueError('MAI devolvió texto sin tiempos; no se puede alinear como evidencia')
    return result


class MaiTranscriber:
    def __init__(self):
        check_mai_authorization()
        self.endpoint = https_endpoint(os.environ['MAI_ENDPOINT']).rstrip('/')
        self.key = os.getenv('MAI_API_KEY')

    def transcribe(self, audio: Path, offset, length, segment_id, raw_response: Path):
        definition = {'enhancedMode': {'enabled': True, 'model': 'MAI-Transcribe-2'},
                      'modelOptions': {'timestamps': 'word', 'transcribeStyle': 'verbatim'},
                      'diarization': {'enabled': os.getenv('MAI_DIARIZATION', 'false').lower() == 'true'}}
        headers = {}
        if self.key:
            headers['Ocp-Apim-Subscription-Key'] = self.key
        else:
            from azure.identity import DefaultAzureCredential
            headers['Authorization'] = 'Bearer ' + DefaultAzureCredential().get_token(
                'https://cognitiveservices.azure.com/.default').token
        with audio.open('rb') as stream:
            response = requests.post(
                self.endpoint + '/speechtotext/transcriptions:transcribe',
                params={'api-version': '2025-10-15'}, headers=headers,
                files={'audio': (audio.name, stream, 'audio/mpeg')},
                data={'definition': json.dumps(definition)}, timeout=(15, 180))
        # Do not log service bodies/URLs which can contain sensitive data.
        if response.status_code in (401, 403):
            raise PendingAuthorization(f'MAI rechazó el acceso (HTTP {response.status_code})')
        if not response.ok:
            raise RuntimeError(f'MAI HTTP {response.status_code}; segmento no confirmado')
        data = response.json()
        raw_response.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return normalize_mai(data, offset, length, segment_id)
