"""Only raw, analysis and delivery. Blob leases coordinate resumable workers."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
try:
    import fcntl
except ImportError:  # Windows local execution. Azure Flex uses Linux.
    fcntl = None
    import msvcrt
import json
import os
from pathlib import Path
import threading
from urllib.parse import quote

STAGES = ('raw', 'analysis', 'delivery')


def json_bytes(data):
    return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')


class LocalStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, stage, name):
        if stage not in STAGES or '..' in Path(name).parts or Path(name).is_absolute():
            raise ValueError('Ruta de artefacto inválida')
        return self.root / stage / name

    def put(self, stage, name, data, *, lease=None, overwrite=True):
        path = self.path(stage, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not overwrite and path.exists():
            raise FileExistsError(name)
        temp = path.with_suffix(path.suffix + '.tmp')
        temp.write_bytes(data)
        temp.replace(path)
        return str(path)

    def get(self, stage, name):
        return self.path(stage, name).read_bytes()

    def exists(self, stage, name):
        return self.path(stage, name).is_file()

    def upload(self, stage, name, path):
        import shutil
        destination = self.path(stage, name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        return str(destination)

    def materialize(self, stage, name, destination):
        return self.path(stage, name)

    def media_source(self, name):
        return str(self.path('raw', name))

    def list_jobs(self):
        return sorted(str(p.relative_to(self.root / 'analysis'))
                      for p in (self.root / 'analysis').glob('*/job.json'))

    @contextmanager
    def claim(self, name):
        path = self.path('analysis', name + '.lock')
        with path.open('a') as lock:
            try:
                if fcntl:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    lock.write('0');lock.flush();lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except (BlockingIOError, OSError):
                yield None
                return
            try:
                yield True
            finally:
                if fcntl:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                else:
                    lock.seek(0);msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


class BlobStore:
    def __init__(self):
        from azure.storage.blob import BlobServiceClient
        connection = os.getenv('AZURE_STORAGE_CONNECTION_STRING')
        self.credential = None
        if connection:
            self.client = BlobServiceClient.from_connection_string(connection)
        else:
            from azure.identity import DefaultAzureCredential
            self.credential = DefaultAzureCredential()
            url = os.getenv('AZURE_STORAGE_ACCOUNT_URL')
            if not url:
                raise ValueError('Falta AZURE_STORAGE_ACCOUNT_URL o AZURE_STORAGE_CONNECTION_STRING')
            self.client = BlobServiceClient(url, credential=self.credential)
        self._lost = threading.Event()
        self._held = False

    def blob(self, stage, name):
        if stage not in STAGES or '..' in Path(name).parts or name.startswith('/'):
            raise ValueError('Ruta de artefacto inválida')
        return self.client.get_blob_client(stage, name)

    def put(self, stage, name, data, *, lease=None, overwrite=True):
        from azure.storage.blob import ContentSettings
        if self._held and self._lost.is_set():
            raise RuntimeError('Lease perdido: no se confirmará el checkpoint')
        self.blob(stage, name).upload_blob(data, overwrite=overwrite, lease=lease,
                                         content_settings=ContentSettings(content_type='application/json'))
        return f'{stage}/{name}'

    def get(self, stage, name):
        return self.blob(stage, name).download_blob().readall()

    def exists(self, stage, name):
        return self.blob(stage, name).exists()

    def upload(self, stage, name, path):
        if self._held and self._lost.is_set():
            raise RuntimeError('Lease perdido: no se guardarán artefactos')
        import mimetypes
        from azure.storage.blob import ContentSettings
        with Path(path).open('rb') as stream:
            self.blob(stage, name).upload_blob(stream, overwrite=True, content_settings=ContentSettings(
                content_type=mimetypes.guess_type(str(path))[0] or 'application/octet-stream'))
        return f'{stage}/{name}'

    def materialize(self, stage, name, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('wb') as stream:
            self.blob(stage, name).download_blob().readinto(stream)
        return destination

    def media_source(self, name):
        # Short-lived read-only SAS, used internally by FFmpeg, never persisted in state.
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas
        now = datetime.now(timezone.utc)
        kwargs = dict(account_name=self.client.account_name, container_name='raw', blob_name=name,
                      permission=BlobSasPermissions(read=True), start=now - timedelta(minutes=5),
                      expiry=now + timedelta(hours=1))
        credential = self.client.credential
        if hasattr(credential, 'account_key'):
            kwargs['account_key'] = credential.account_key
        else:
            kwargs['user_delegation_key'] = self.client.get_user_delegation_key(
                now - timedelta(minutes=5), now + timedelta(hours=1))
        sas = generate_blob_sas(**kwargs)
        return self.blob('raw', name).url + '?' + sas

    def list_jobs(self):
        return [b.name for b in self.client.get_container_client('analysis').list_blobs()
                if b.name.endswith('/job.json')]

    @contextmanager
    def claim(self, name):
        from azure.core.exceptions import HttpResponseError
        blob = self.blob('analysis', name)
        try:
            lease = blob.acquire_lease(lease_duration=60)
        except HttpResponseError as exc:
            if exc.status_code == 409:
                yield None
                return
            raise
        stop = threading.Event()
        self._lost.clear()
        self._held = True

        def renew():
            while not stop.wait(20):
                try:
                    lease.renew()
                except Exception:
                    self._lost.set()
                    return

        thread = threading.Thread(target=renew, daemon=True)
        thread.start()
        try:
            yield lease
        finally:
            self._held = False
            stop.set()
            thread.join(timeout=5)
            try:
                lease.release()
            except HttpResponseError:
                pass


def read_json(store, stage, name):
    return json.loads(store.get(stage, name))
