from dataclasses import asdict, dataclass
import os
from urllib.parse import urlparse
from dotenv import load_dotenv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')


@dataclass(frozen=True)
class Settings:
    segment_seconds: int = 120
    frame_every_seconds: int = 10
    batch_size: int = 4
    transcription_provider: str = 'supplied'
    use_ai: bool = True
    speaker: str = ''
    rules: str = ''
    deployment: str = ''
    api_base_url: str = ''

    def __post_init__(self):
        if not 1 <= self.segment_seconds <= 600:
            raise ValueError('SEGMENT_SECONDS debe estar entre 1 y 600')
        if not 1 <= self.frame_every_seconds <= self.segment_seconds:
            raise ValueError('FRAME_EVERY_SECONDS debe estar entre 1 y SEGMENT_SECONDS')
        if not 1 <= self.batch_size <= 16:
            raise ValueError('VISION_BATCH_SIZE debe estar entre 1 y 16')
        if self.transcription_provider not in ('supplied', 'mai'):
            raise ValueError('TRANSCRIPTION_PROVIDER debe ser supplied o mai')
        if self.use_ai and not self.deployment:
            raise ValueError('Falta AZURE_VISION_DEPLOYMENT: nombre del deployment existente')
        if self.use_ai:
            https_endpoint(self.api_base_url, v1=True)

    @classmethod
    def from_env(cls, **overrides):
        values = dict(segment_seconds=int(os.getenv('SEGMENT_SECONDS', '120')),
                      frame_every_seconds=int(os.getenv('FRAME_EVERY_SECONDS', '10')),
                      batch_size=int(os.getenv('VISION_BATCH_SIZE', '4')),
                      transcription_provider=os.getenv('TRANSCRIPTION_PROVIDER', 'supplied'),
                      deployment=os.getenv('AZURE_VISION_DEPLOYMENT', ''),
                      api_base_url=os.getenv('AZURE_OPENAI_BASE_URL', ''))
        values.update(overrides)
        return cls(**values)

    def as_dict(self):
        return asdict(self)


def https_endpoint(value, *, v1=False):
    parsed = urlparse(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query:
        raise ValueError('Se requiere endpoint HTTPS sin credenciales ni query string')
    if v1 and not parsed.path.rstrip('/').endswith('/openai/v1'):
        raise ValueError('AZURE_OPENAI_BASE_URL debe terminar en /openai/v1/')
    return value.rstrip('/') + '/'
