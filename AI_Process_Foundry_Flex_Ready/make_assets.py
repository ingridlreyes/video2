import cv2,json
import numpy as np
from PIL import Image, ImageDraw
from pathlib import Path
from poc_core import get_font,ROOT
p=ROOT/'assets';p.mkdir(exist_ok=True)
W,H=1280,720
NAV=(20,38,68);BLUE=(36,111,211);MINT=(19,141,138)

def rect(d, xy, fill, rad=0,outline=None,width=1):
 if rad:d.rounded_rectangle(xy,radius=rad,fill=fill,outline=outline,width=width)
 else:d.rectangle(xy,fill=fill,outline=outline,width=width)
def text(d,xy,s,size=20,color=NAV,bold=False): d.text(xy,s,fill=color,font=get_font(size,bold))
def frame(step):
 im=Image.new('RGB',(W,H),(247,249,252));d=ImageDraw.Draw(im)
 rect(d,(0,0,W,72),(255,255,255));rect(d,(0,0,12,H),BLUE)
 rect(d,(27,21,63,53),BLUE,9);text(d,(36,23),'@',22,(255,255,255),True)
 text(d,(79,22),'Correo Demo',25,NAV,True)
 rect(d,(310,18,892,56),(241,244,248),12);text(d,(338,27),'Buscar en correo...',17,(117,127,140))
 rect(d,(23,94,255,H-26),(238,244,251),13)
 rect(d,(40,146,223,201),BLUE,12);text(d,(60,160),'+  Nuevo correo',19,(255,255,255),True)
 for i,t in enumerate(['Recibidos','Enviados','Borradores','Archivados']):
  yy=243+i*53;text(d,(56,yy),t,19,NAV,i==0)
 rect(d,(283,94,1250,H-26),(255,255,255),12)
 text(d,(316,115),'Bandeja de entrada',27,NAV,True)
 for i,(sender,subject) in enumerate([('Operaciones','Reporte semanal'),('Capacitacion','Material de induccion'),('Soporte','Solicitud de acceso'),('Analitica','Actualizacion de indicadores'),('Proyectos','Minuta de seguimiento')]):
  y=171+i*85
  d.line((315,y+68,1220,y+68),fill=(235,241,247),width=2)
  text(d,(326,y+5),sender,19,NAV,True)
  text(d,(326,y+33),subject,17,(102,116,135))
  text(d,(1070,y+20),f'{11+i}:20',14,(125,138,151))
 if step>=2:
  rect(d,(620,147,1217,677),(255,255,255),16,outline=(210,223,238),width=3)
  rect(d,(620,147,1217,209),NAV,13)
  text(d,(650,165),'Mensaje nuevo',22,(255,255,255),True)
  text(d,(642,232),'Para:',19,NAV,True)
  rect(d,(707,223,1183,265),(255,255,255),5,outline=(184,201,222),width=2)
  if step>=3:text(d,(720,232),'usuario@empresa.com',18,NAV)
  text(d,(642,299),'Asunto:',19,NAV,True)
  rect(d,(735,289,1183,335),(255,255,255),5,outline=(184,201,222),width=2)
  if step>=4:text(d,(747,302),'Seguimiento de capacitacion',17,NAV)
  rect(d,(642,359,1182,576),(247,250,253),5)
  if step>=4:
   text(d,(653,382),'Hola,',18,NAV)
   text(d,(653,424),'Comparto los materiales de la sesion.',17,NAV)
   text(d,(653,465),'Saludos.',17,NAV)
  rect(d,(644,605,765,654),BLUE,10);text(d,(666,620),'Enviar',18,(255,255,255),True)
  text(d,(795,618),'Adjuntar   |   Formato',15,(102,116,135))
 # fictitious interface watermark to avoid misidentifying
 text(d,(1040,26),'INTERFAZ FICTICIA',12,(143,154,169),True)
 return im

steps=[
 {'title':'Crear un mensaje','instruction':'Selecciona «Nuevo correo» para abrir el editor de mensajes.',
  'detail':'El botón se encuentra en el panel izquierdo de la bandeja.', 'second':0,'bbox':[40/1280,146/720,183/1280,55/720],'target_label':'Nuevo correo'},
 {'title':'Definir el destinatario','instruction':'En el campo «Para», escribe el correo de la persona destinataria.',
  'detail':'Confirma que el destinatario es correcto antes de continuar. Nunca uses datos reales en el ejemplo.', 'second':6,'bbox':[707/1280,223/720,476/1280,42/720],'target_label':'Campo Para'},
 {'title':'Escribir asunto y mensaje','instruction':'Completa el asunto e incorpora el contenido del mensaje.',
  'detail':'Utiliza información autorizada; verifica redacción y archivos adjuntos, si los hay.', 'second':12,'bbox':[735/1280,289/720,448/1280,46/720],'target_label':'Asunto'},
 {'title':'Enviar el correo','instruction':'Revisa destinatario, asunto y contenido; después selecciona «Enviar».',
  'detail':'El envío es una acción irreversible en algunos sistemas. Valida la información antes de confirmarlo.', 'second':18,'bbox':[644/1280,605/720,121/1280,49/720],'target_label':'Enviar'}]
for i,st in enumerate(steps,1):
 fn=f'assets/paso_{i:02d}.jpg';frame(i).save(ROOT/fn,quality=94);st['image']=fn;st['review_required']=False
process={'title':'Cómo enviar un correo en Correo Demo','goal':'Enviar un mensaje mediante la interfaz ficticia Correo Demo.',
         'prerequisites':'Tener una sesión iniciada en la plataforma y permisos para enviar mensajes.',
         'rules_summary':'Solo voz instructora; excluir conversación informal y dudas del proceso principal.',
         'rules':['Incluir únicamente instrucciones impartidas por el instructor previamente identificado.',
                  'Omitir comentarios, saludos e interrupciones del flujo principal.',
                  'Registrar preguntas frecuentes en un apartado separado solo si el usuario lo habilita.',
                  'Nunca documentar contraseñas, datos personales o tokens expuestos en la grabación.'],
         'steps':steps}
(ROOT/'example_steps.json').write_text(json.dumps(process,ensure_ascii=False,indent=2),encoding='utf-8')
# simulate silent screen recording, changing views every six seconds. The screenshots are synthetic.
video=str(ROOT/'assets'/'video_demo_ficticio.mp4')
vw=cv2.VideoWriter(video,cv2.VideoWriter_fourcc(*'mp4v'),3,(W,H))
for image_i in range(1,5):
 image=cv2.imread(str(ROOT/'assets'/f'paso_{image_i:02d}.jpg'))
 for _ in range(18):vw.write(image)
vw.release()
print('Created',video)
