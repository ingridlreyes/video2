"""Real FFmpeg execution for 5m/1h/5h timeline fixtures; no inference or API mocks.

Fixtures are explicitly synthetic low-bitrate videos, testing duration/segmentation,
not semantic accuracy on human recordings or performance of Foundry.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.media import ffmpeg
from real_pipeline import run_pipeline


def verify(durations):
    report = {'test_type': 'real_local_media_synthetic_fixtures_without_ai', 'cases': []}
    with tempfile.TemporaryDirectory(prefix='long-video-check-') as directory:
        root = Path(directory)
        os.environ['PIPELINE_DATA_DIR'] = str(root / 'runs')
        os.environ['USE_AZURE_BLOB'] = 'false'
        for length in durations:
            video = root / f'fixture_{length}s.mp4'
            # Low fps/small dimensions keep a real five-hour container practical in CI.
            subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                            '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=1', '-t', str(length),
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '40', str(video)], check=True)
            start = time.monotonic()
            result = run_pipeline(str(video), use_ai=False)
            if result['status'] != 'extracted_without_ai':
                raise AssertionError(result.get('error', result))
            manifest = json.loads(Path(result['manifest']).read_text())
            assert abs(manifest['video_duration_seconds'] - length) < .01
            assert abs(manifest['processed_seconds'] - length) < .01
            assert manifest['coverage'][0]['start'] == 0
            assert manifest['coverage'][-1]['end'] == length
            assert all(a['end'] == b['start'] for a, b in zip(manifest['coverage'], manifest['coverage'][1:]))
            assert all(row['frames'] > 0 for row in manifest['coverage'])
            assert manifest['steps'] == [] and result['pptx'] is None
            case = {'duration_seconds': length, 'processed_seconds': manifest['processed_seconds'],
                    'segments': len(manifest['coverage']), 'frames': manifest['frame_candidates'],
                    'extraction_wall_seconds': round(time.monotonic() - start, 2), 'status': 'passed'}
            report['cases'].append(case)
            print(json.dumps(case), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--durations', nargs='+', type=int, default=[300, 3600, 18000])
    parser.add_argument('--output', default='docs/long_video_report.json')
    args = parser.parse_args()
    result = verify(args.durations)
    Path(args.output).write_text(json.dumps(result, indent=2))
