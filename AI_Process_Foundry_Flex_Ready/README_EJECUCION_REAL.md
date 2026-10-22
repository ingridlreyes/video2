# Pipeline de video completo · Foundry y Azure Functions Flex Consumption

Esta base procesa la duración completa mediante el mismo motor local y en Azure Functions. GPT-6.1 Sol es el modelo de interpretación; su **deployment existente** se configura por variable de entorno. MAI-Transcribe-2 permanece pendiente de autorización. Se aceptan VTT, SRT y JSON mientras tanto.

## Preparar la otra laptop

Requiere Python 3.11+ (para Azure, usar la versión configurada en la Function App). No copiar `.venv` entre equipos. FFmpeg se incluye mediante `imageio-ffmpeg`; puede reemplazarse con `FFMPEG_PATH`.

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell, en lugar de la línea anterior:
# .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python scripts/configure.py
```

Editar `.env` con estos tres valores:

```dotenv
AZURE_OPENAI_BASE_URL=https://<recurso>.openai.azure.com/openai/v1/
AZURE_OPENAI_API_KEY=<clave local>
AZURE_VISION_DEPLOYMENT=<nombre exacto del deployment existente de GPT-6.1 Sol>
```

El nombre del deployment no se deduce ni tiene valor predeterminado. Sin clave, el cliente admite `DefaultAzureCredential` para la identidad autorizada. El código no crea deployments ni servicios Azure.

Comprobar acceso real antes de ejecutar un video:

```bash
python scripts/check_integrations.py
python run_real.py --video /ruta/grabacion.mp4 --transcript /ruta/grabacion.vtt
# También acepta .srt o .json:
python run_real.py --video /ruta/grabacion.mp4 --transcript /ruta/grabacion.srt
```

El diagnóstico realiza una petición real a Responses v1 con imagen y JSON Schema estricto, valida el color de una imagen de diagnóstico y comprueba que `response.model` reporta GPT-6.1 Sol. Si falla, no se llama al análisis. Esa imagen no se usa como evidencia de procedimientos. Se rechazan respuestas incompletas, negativas, sin JSON o fuera del esquema. No existe fallback a otro modelo ni transcriptor.

Sin credenciales se puede comprobar la extracción real:

```bash
python run_real.py --video assets/video_demo_ficticio.mp4 --no-ai
python -m unittest discover -s tests -v
python scripts/verify_long_videos.py
```

`--no-ai` termina en `extracted_without_ai`: genera evidencias y manifiesto, **no inventa pasos ni documentos inferidos**. Los videos incluidos/generados para QA son sintéticos y no demuestran calidad de interpretación en grabaciones humanas.

Interfaz opcional:

```bash
python -m pip install -r requirements-real.txt
python web_real.py
```

## Segmentación, checkpoints y documentos

Valores iniciales: segmentos de 120 segundos, una captura cada 10 segundos, lotes de 4 imágenes. No hay máximo global de minutos o de capturas. Los antiguos parámetros `--limit-minutes` y `--max-frames` se eliminaron; la API Python rechaza esos argumentos con un error explícito. El intervalo de muestreo determina qué acciones rápidas pueden perderse: recorrer toda la duración no equivale a observar cada fotograma.

```bash
python run_real.py --video grabacion.mp4 --transcript grabacion.json --segment-seconds 120 --frame-every-seconds 5
python run_real.py --resume proc-<identificador>
```

Cada trabajo persiste configuración, capacidad verificada, duración, plan completo, capturas, transcripción y resultados. Las unidades son: verificación del modelo, preparación del segmento, un lote de inferencia y un volumen documental. Un fallo se conserva como `failed` o `pending_authorization`; el reintento es explícito. Las unidades ya confirmadas se reutilizan. Si se pierde el host justo después de una respuesta de IA pero antes de guardar el checkpoint, esa petición puede repetirse: no se promete facturación exactamente una vez.

Se conserva toda la transcripción de cada segmento sin cortes por cantidad de caracteres. El proveedor puede rechazar entradas excesivas; el trabajo falla de forma visible en vez de recortar texto. Los IDs de hablantes de una transcripción suministrada deben corresponder al video. El filtro `--speaker` requiere un ID presente; no identifica personas por inferencia.

El manifiesto `analysis/<id>/procedure.json` incluye duración, segundos recorridos, cobertura por segmento, intervalo, capturas y pasos con tiempos absolutos. Por defecto, se generan partes de hasta 40 pasos para acotar memoria y disco temporal; **todas** se enumeran en `delivery/<id>/index.json`. La salida CLI contiene `files` con todas las partes; `pptx`/`docx` son accesos a la primera por compatibilidad.

PowerPoint conserva las capturas como imágenes y los recuadros, flechas y textos como objetos nativos editables. Los mapas se paginan, las notas conservan evidencia y la numeración continúa entre partes. Las salidas de cada ejecución usan carpetas propias para evitar reutilizar anotaciones de otros trabajos. Los documentos se entregan como borradores para revisión.

## Blob Storage y Flex Consumption

Solo se usan los servicios contemplados: el recurso Foundry existente, Blob Storage y la Function App Flex Consumption. Los datos usan los contenedores privados existentes `raw`, `analysis`, `delivery`; el motor presupone estos contenedores. Si aún faltan, `python scripts/prepare_storage.py` crea únicamente esos tres contenedores privados en la cuenta configurada; no crea otra cuenta ni servicios.

Para persistir la CLI en Blob:

```dotenv
USE_AZURE_BLOB=true
AZURE_STORAGE_CONNECTION_STRING=<conexión de la cuenta existente>
# Alternativa sin clave:
# AZURE_STORAGE_ACCOUNT_URL=https://<cuenta>.blob.core.windows.net
```

Con identidad administrada/Azure CLI, autorizar operaciones Blob y generación de SAS de delegación de usuario en la cuenta existente. El motor accede al video con una SAS interna temporal de solo lectura y FFmpeg lee rangos HTTP: no descarga el video de cinco horas completo al disco temporal. La cuenta debe ser accesible desde la Function App y permitir la autorización configurada. No se persisten ni devuelven las SAS.

`function_app.py` expone:

| Método/ruta | Uso |
| --- | --- |
| `POST /api/jobs` | Crear trabajo con referencias a archivos ya cargados en `raw`; devuelve 202 |
| `GET /api/jobs/<id>` | Estado, cobertura parcial y entregas |
| `POST /api/jobs/<id>/retry` | Volver a poner en procesamiento una unidad fallida |
| Temporizador | Avanzar una unidad por ejecución, con lease renovable en Blob |

Ejemplo del cuerpo de creación:

```json
{"video_blob":"entrada/grabacion.mp4","transcript_blob":"entrada/grabacion.vtt","speaker":"","rules":"Documentar solo acciones evidenciadas"}
```

Configurar en `local.settings.json` para `func start`, o en Application Settings de Azure:

- Los mismos valores de Foundry y procesamiento de `.env`.
- La conexión de datos `AZURE_STORAGE_CONNECTION_STRING` (o URL + identidad).
- `AzureWebJobsStorage`, la cuenta existente para el host de Functions y el temporizador; admite la configuración equivalente de identidad del host.
- `PIPELINE_POLL_SCHEDULE=0 */1 * * * *` como inicio (una ejecución por minuto).

El host de Functions administra sus propios blobs/containers de host y despliegue en la cuenta existente. Los contenedores de negocio siguen siendo los tres indicados. No se requiere Event Grid, Service Bus, Storage Queues, Durable Functions, Video Indexer ni cómputo basado en contenedores.

Para ejecutar el host local, instalar Azure Functions Core Tools v4 y usar:

```bash
python scripts/configure.py --sync-functions
func start
# Alternativa para una unidad concreta, usando .env y la cuenta real:
python scripts/worker_once.py proc-<identificador>
```

Para publicar en la **Function App Flex Consumption contemplada**, una vez creada/autorizada por el equipo:

```bash
func azure functionapp publish <nombre-function-app-existente>
```

Core Tools solicita compilación remota para Python; no publicar dependencias de una `.venv` de Windows/macOS en Linux. El proyecto incluye `host.json` y `.funcignore`. No se ha desplegado desde esta laptop.

El temporizador es intencionalmente secuencial y rota entre trabajos por última actualización. Es una base de capacidad inicial, no un sistema de alto volumen: otros workers pueden reutilizar el mismo motor y leases sin cambiar visión, transcripción ni exportación. Las llamadas HTTP solo crean/consultan trabajos y no esperan horas de procesamiento. Hay límites explícitos de tiempo por subprocess/API; ante límites de disco, formato, conectividad o cuota, el trabajo falla y se reanuda desde su checkpoint.

## Activar MAI cuando esté autorizado

No cambiar código de análisis ni exportación. En la nueva laptop o Application Settings:

```dotenv
TRANSCRIPTION_PROVIDER=mai
MAI_AUTHORIZED=true
MAI_ENDPOINT=https://<recurso-autorizado>.cognitiveservices.azure.com
MAI_API_KEY=<clave>
MAI_DIARIZATION=false
```

`MAI_ENDPOINT` es la raíz del recurso autorizado, no un endpoint `/openai/v1` ni un nombre de deployment. El contrato consultado selecciona `MAI-Transcribe-2` en `enhancedMode.model`, con `enhancedMode.enabled=true`, petición multipart `audio` + `definition`, API `2025-10-15`. Se normalizan `phrases`, `offsetMilliseconds`, `durationMilliseconds` y `speaker` a segundos absolutos. La respuesta real se conserva en `analysis`; faltas de tiempos/contrato provocan error, no tiempos inventados.

MAI está en preview y su integración **no está validada en vivo** aquí. Las páginas oficiales tienen ejemplos inconsistentes sobre la ubicación de `modelOptions`; el adaptador sigue la tabla de parámetros y el ejemplo del repositorio oficial (nivel raíz). Confirmar el comportamiento con audio real del recurso autorizado antes de usarlo operativamente. El adaptador no prueba otro formato silenciosamente.

Si se activa diarización, los IDs se delimitan por segmento (`segment_000001:0`): no se presume que el hablante 0 sea la misma persona entre llamadas. Para filtrar un instructor a lo largo de toda la grabación, suministrar una transcripción con identidad consistente. No se agrega un servicio de diarización.

```bash
python scripts/check_integrations.py --audio /ruta/audio-real-corto.mp3
python run_real.py --video /ruta/video.mp4
```

Una transcripción suministrada tiene prioridad incluso con `TRANSCRIPTION_PROVIDER=mai`. Para reanudar un trabajo que ya eligió MAI, habilitar autorización/credenciales y usar `--resume`; para cambiar de proveedor, crear un trabajo nuevo. La selección queda registrada por trabajo.

## Verificación entregada

- `docs/long_video_report.json`: ejecución de FFmpeg sobre archivos sintéticos reales de 300, 3,600 y 18,000 segundos, sin modelo. Cobertura completa; 30, 360 y 1,800 capturas.
- `tests/`: contratos, esquemas, timestamps, segmentación, extracción real, reanudación y editabilidad de PowerPoint.
- `docs/integration_report.json`: Foundry/Blob no verificados por falta de configuración; MAI pendiente. El diagnóstico devuelve código 2 cuando Foundry no está verificado.
- Se indexaron las cuatro funciones Python con el SDK. Esto no sustituye ejecutar Core Tools o probar el despliegue Linux con recursos reales.

No se afirma que el pipeline de IA completo esté validado hasta ejecutar las comprobaciones reales en el equipo con credenciales.

## Fuentes oficiales consultadas · 22 de octubre de 2026

- [GPT-6.1 Sol: modalidades y Structured Outputs](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
- [Responses v1 en Foundry: modelos, autenticación e imágenes](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/responses)
- [MAI-Transcribe: parámetros y activación](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/mai-transcribe)
- [Contrato REST Speech 2025-10-15: multipart y respuesta](https://learn.microsoft.com/en-us/rest/api/speechtotext/transcriptions/transcribe?view=rest-speechtotext-2025-10-15)
- [Ejemplo oficial MAI-Transcribe-2](https://github.com/microsoft-foundry/model-releases/tree/main/models/microsoft-ai/mai-transcribe-2)
- [Flex Consumption y publicación con compilación remota](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-how-to)
