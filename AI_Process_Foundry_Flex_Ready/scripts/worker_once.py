"""Run one Functions processing unit locally against existing Blob jobs."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.jobs import advance_job
from engine.storage import BlobStore

if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Uso: python scripts/worker_once.py proc-<id>')
    print(json.dumps(advance_job(BlobStore(), sys.argv[1]), indent=2, ensure_ascii=False))
