"""Microsoft Graph application-permission adapter for scheduled Teams meetings.

No bearer tokens in forms/logs. Azure DefaultAzureCredential on backend.
This is NOT an unauthenticated downloader for pasted Teams share links.
"""
from __future__ import annotations
import os
from pathlib import Path
from urllib.parse import quote
import requests
from transcript_ingestion import vtt_to_segments

BASE='https://graph.microsoft.com/v1.0'
MAX_RECORDING_BYTES=10*1024**3

class GraphTeamsError(RuntimeError): pass


def graph_token():
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as e:
        raise GraphTeamsError('Instala azure-identity y configura Managed Identity o az login.') from e
    return DefaultAzureCredential(exclude_interactive_browser_credential=True).get_token('https://graph.microsoft.com/.default').token

class TeamsGraphClient:
    def __init__(self, token_provider=graph_token, session=None):
        self.token_provider=token_provider
        self.session=session or requests.Session()

    def _get(self,path,accept='application/json',stream=False):
        # Endpoint path is generated from Graph meeting/recording identifiers only.
        url=BASE+'/'+path.lstrip('/')
        resp=self.session.get(url,headers={'Authorization':f'Bearer {self.token_provider()}', 'Accept':accept},
                              timeout=(15,120),stream=stream,allow_redirects=False)
        if resp.status_code in (301,302,303,307,308):
            resp.close()
            raise GraphTeamsError('Graph devolvió una redirección; no se reenvían tokens a otros hosts.')
        if resp.status_code >= 400:
            try:
                err=resp.json().get('error',{})
                code=err.get('innerError',{}).get('code') or err.get('code')
            except Exception:code=f'HTTP {resp.status_code}'
            resp.close()
            raise GraphTeamsError(f'Microsoft Graph no autorizó la operación ({code}).')
        return resp

    def _list_items(self, path):
        result=self._get(path)
        try:return result.json().get('value',[])
        finally: result.close()

    @staticmethod
    def _base(organizer_user_id, online_meeting_id):
        # URL encode every id segment, including a Graph meeting id with special characters.
        if not organizer_user_id or not online_meeting_id:raise GraphTeamsError('Falta organizer ID o online meeting ID.')
        return f'users/{quote(str(organizer_user_id),safe="")}/onlineMeetings/{quote(str(online_meeting_id),safe="")}'

    def list_artifacts(self, organizer_user_id, online_meeting_id):
        base=self._base(organizer_user_id,online_meeting_id)
        return {'recordings':self._list_items(base+'/recordings'),
                'transcripts':self._list_items(base+'/transcripts')}

    def fetch_transcript(self,organizer_user_id,online_meeting_id,transcript_id):
        path=self._base(organizer_user_id,online_meeting_id)+'/transcripts/'+quote(str(transcript_id),safe='')+'/content'
        try:
            response=self._get(path,accept='text/vtt')
            try:return response.content.decode('utf-8-sig'),'text/vtt'
            finally:response.close()
        except GraphTeamsError as exc:
            if 'SpeakerAttributionNotAllowed' not in str(exc):raise
            # Tenant policy disallows attribution; preserve timestamps but no speaker names.
            response=self._get(path,accept='application/vnd.microsoft.graph.transcript+text')
            try:return response.content.decode('utf-8-sig'),'unattributed'
            finally:response.close()

    def fetch_recording(self,organizer_user_id,online_meeting_id,recording_id,destination:Path):
        path=self._base(organizer_user_id,online_meeting_id)+'/recordings/'+quote(str(recording_id),safe='')+'/content'
        response=self._get(path,accept='video/mp4',stream=True)
        destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
        read=0
        try:
            with destination.open('wb') as out:
                for chunk in response.iter_content(chunk_size=1024*1024):
                    if not chunk:continue
                    read+=len(chunk)
                    if read>MAX_RECORDING_BYTES:raise GraphTeamsError('Grabación supera límite de seguridad local de 10 GiB.')
                    out.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally:response.close()
        return destination

    def download(self,organizer_user_id,online_meeting_id,directory,transcript_id=None,recording_id=None):
        artifacts=self.list_artifacts(organizer_user_id,online_meeting_id)
        recordings=artifacts['recordings']
        transcripts=artifacts['transcripts']
        if not recordings:raise GraphTeamsError('Esta reunión no tiene grabación accesible mediante Graph.')
        if recording_id is None:recording_id=recordings[-1]['id']
        if transcript_id is None and transcripts:transcript_id=transcripts[-1]['id']
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        video=self.fetch_recording(organizer_user_id,online_meeting_id,recording_id,directory/'teams_recording.mp4')
        transcript_path=None;format_name=None
        if transcript_id:
            contents,format_name=self.fetch_transcript(organizer_user_id,online_meeting_id,transcript_id)
            transcript_path=directory/('teams_transcript.vtt' if format_name=='text/vtt' else 'teams_transcript.txt')
            transcript_path.write_text(contents,encoding='utf-8')
        return {'video_path':str(video),'transcript_path':str(transcript_path) if transcript_path else None,
                'transcript_format':format_name,'recording_id':recording_id,'transcript_id':transcript_id}
