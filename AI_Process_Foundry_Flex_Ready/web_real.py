"""Gradio demo UI for backend-owned testing; external corporate frontend is not assumed."""
from pathlib import Path
import gradio as gr
from real_pipeline import run_pipeline


def process(video,transcript,main_speaker,rules,enable_ai,frame_every):
    """Convert uploaded media into reviewed-ready documents, or an explicit no-evidence message."""
    if not video:return 'Selecciona un MP4',None,None,None
    try:
        result=run_pipeline(video,transcript or None,main_speaker.strip(),rules,enable_ai,frame_every_seconds=int(frame_every))
        status=f"Estado: {result['status']}. Capturas: {result['frames']}. Pasos: {result['steps']}."
        if result.get('error'):status+=' '+str(result['error'])
        status+=f" Trabajo: {result['project_id']}"
        if result.get('manifest') and not Path(result['manifest']).is_file():
            return status+' Artefactos guardados en Blob; descargar con cliente autorizado de Storage.',None,None,None
        return status,[f['pptx'] for f in result.get('files',[])],[f['docx'] for f in result.get('files',[])],result.get('manifest')
    except Exception as error:
        return f'ERROR: {type(error).__name__}: {error}',None,None,None

with gr.Blocks(title='AI Process Documentation · Procesamiento segmentado') as demo:
    gr.Markdown('# Video → Procedimientos → PowerPoint editable\nDemo real de backend. Utiliza Azure OpenAI y opcionalmente Azure Blob Storage; no usa datos simulados.')
    video=gr.File(label='Grabación MP4 (duración completa)',file_types=['.mp4'],type='filepath')
    transcript=gr.File(label='Transcripción VTT, SRT o JSON con tiempos',file_types=['.vtt','.srt','.json'],type='filepath')
    speaker=gr.Textbox(label='Hablante instructor (ID opcional)',placeholder='Ej.: Speaker 1 / instructor@example.com')
    rules=gr.Textbox(label='Reglas de extracción',lines=3,value='Ignorar charlas fuera del procedimiento. No inventar pasos ni botones.')
    use_ai=gr.Checkbox(label='Usar IA real de Azure OpenAI',value=True)
    frames=gr.Slider(1,60,value=10,step=1,label='Intervalo entre capturas (segundos)')
    btn=gr.Button('Analizar y generar documentos',variant='primary')
    status=gr.Textbox(label='Resultado')
    pptx=gr.File(label='PowerPoint editable (todas las partes)',file_count='multiple')
    docx=gr.File(label='Guía Word (todas las partes)',file_count='multiple')
    manifest=gr.File(label='JSON de evidencias')
    btn.click(process,[video,transcript,speaker,rules,use_ai,frames],[status,pptx,docx,manifest])
if __name__=='__main__':demo.launch()
