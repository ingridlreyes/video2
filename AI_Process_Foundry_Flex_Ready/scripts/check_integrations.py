"""Honest live checks: never count a skipped integration as passed."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.config import Settings
from engine.storage import BlobStore
from engine.transcription import MaiTranscriber, PendingAuthorization
from engine.vision import azure_client, verify_capabilities


def check(audio=None):
    report = {}
    try:
        settings = Settings.from_env()
        report['foundry'] = {'status': 'passed_live', **verify_capabilities(azure_client(), settings.deployment)}
    except Exception as exc:
        report['foundry'] = {'status': 'unverified', 'reason': type(exc).__name__,
                             'configuration_present': bool(os.getenv('AZURE_OPENAI_BASE_URL')) and
                             bool(os.getenv('AZURE_VISION_DEPLOYMENT'))}
    if os.getenv('AZURE_STORAGE_ACCOUNT_URL') or os.getenv('AZURE_STORAGE_CONNECTION_STRING'):
        try:
            store = BlobStore()
            # Live read-only access check for each pre-existing container.
            for name in ('raw', 'analysis', 'delivery'):
                store.client.get_container_client(name).get_container_properties()
            report['blob'] = {'status': 'passed_live_read_only', 'containers': ['raw', 'analysis', 'delivery']}
        except Exception as exc:
            report['blob'] = {'status': 'unverified', 'reason': type(exc).__name__}
    else:
        report['blob'] = {'status': 'unverified', 'reason': 'No storage endpoint/connection configured'}
    try:
        adapter = MaiTranscriber()
        if not audio:
            report['mai'] = {'status': 'unverified', 'reason': 'Authorized configuration; no real audio supplied'}
        else:
            from engine.media import run
            # Explicit operator-provided short MP3, not a fake API payload.
            import tempfile
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'mai_response.json'
                rows = adapter.transcribe(Path(audio), 0, 600, 'live-check', output)
                report['mai'] = {'status': 'passed_live', 'segments': len(rows)}
    except PendingAuthorization as exc:
        report['mai'] = {'status': 'pending_authorization', 'reason': str(exc)}
    except Exception as exc:
        report['mai'] = {'status': 'unverified', 'reason': type(exc).__name__}
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio', help='MP3 real, máximo 10 minutos; solo con MAI autorizado')
    parser.add_argument('--output', default='docs/integration_report.json')
    args = parser.parse_args()
    report = check(args.audio)
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report['foundry']['status'] == 'passed_live' else 2)
