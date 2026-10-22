"""Bounded temporal segments; FFmpeg can read private Blob SAS URLs via HTTP ranges."""
import math
import os
from pathlib import Path
import re
import shutil
import subprocess


def ffmpeg():
    configured = os.getenv('FFMPEG_PATH')
    if configured:
        return configured
    installed = shutil.which('ffmpeg')
    if installed:
        return installed
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args, *, probe=False):
    try:
        result = subprocess.run([ffmpeg(), '-nostdin', '-hide_banner', *args],
                                capture_output=True, timeout=int(os.getenv('MEDIA_TIMEOUT_SECONDS', '180')))
    except subprocess.TimeoutExpired:
        raise RuntimeError('FFmpeg excedió el tiempo permitido; trabajo reanudable') from None
    if not probe and result.returncode:
        # stderr can expose a signed Blob URL; keep it out of logs and HTTP responses.
        raise RuntimeError('FFmpeg no pudo leer/procesar el medio; revisar formato, acceso y binario')
    return result.stderr.decode(errors='replace')


def duration(source):
    diagnostic = run(['-i', str(source)], probe=True)
    match = re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)', diagnostic)
    if not match or 'Video:' not in diagnostic:
        raise ValueError('No se pudo verificar la duración y pista de video')
    hours, minutes, seconds = map(float, match.groups())
    value = hours * 3600 + minutes * 60 + seconds
    if not math.isfinite(value) or value <= 0:
        raise ValueError('Duración inválida')
    return value


def plan_segments(total, segment_seconds):
    if not math.isfinite(total) or total <= 0 or segment_seconds <= 0:
        raise ValueError('Duración/tamaño de segmento inválido')
    return [{'index': i, 'start': i * segment_seconds,
             'end': min(total, (i + 1) * segment_seconds)}
            for i in range(math.ceil(total / segment_seconds))]


def extract_frames(source, segment, folder, every):
    folder.mkdir(parents=True, exist_ok=True)
    length = segment['end'] - segment['start']
    run(['-loglevel', 'error', '-y', '-ss', str(segment['start']), '-i', str(source),
         '-t', str(length), '-an', '-vf',
         f'fps=1/{every}:start_time=0:round=up,scale=\'min(1600,iw)\':-2',
         '-q:v', '3', '-start_number', '0', str(folder / 'frame_%06d.jpg')])
    paths = sorted(folder.glob('frame_*.jpg'))
    expected = math.ceil(length / every)
    if len(paths) != expected:
        raise RuntimeError(f'Cobertura visual incompleta: esperadas {expected} capturas, obtenidas {len(paths)}')
    return [{'image': str(p), 'second': segment['start'] + i * every} for i, p in enumerate(paths)]


def extract_audio(source, segment, target):
    run(['-loglevel', 'error', '-y', '-ss', str(segment['start']), '-i', str(source),
         '-t', str(segment['end'] - segment['start']), '-vn', '-ac', '1', '-ar', '16000',
         '-b:a', '48k', str(target)])
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError('No se pudo extraer audio del segmento')
