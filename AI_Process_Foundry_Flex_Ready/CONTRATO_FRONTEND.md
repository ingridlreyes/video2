# Contrato del frontend · API Functions v2

Subir el video y su VTT/SRT/JSON a `raw` de la cuenta existente. Las llamadas Functions usan la autenticación Function configurada en el entorno. No enviar videos completos al endpoint HTTP.

## Crear

`POST /api/jobs`

```json
{"video_blob":"entrada/grabacion.mp4","transcript_blob":"entrada/grabacion.vtt","speaker":"","rules":"Solo acciones evidenciadas","title":"Procedimiento"}
```

Respuesta HTTP 202:

```json
{"project_id":"proc-<16 caracteres hex>","status":"queued","status_path":"/api/jobs/proc-<id>"}
```

La transcripción es obligatoria mientras `TRANSCRIPTION_PROVIDER=supplied`. Sin transcripción ni MAI autorizado: HTTP 409 `pending_authorization`. El nombre de deployment, los parámetros del motor y credenciales se configuran en el backend.

## Consultar y reintentar

`GET /api/jobs/<id>` devuelve estado, plan `segments`, `next_segment`, capacidad del modelo verificada, `deliveries`, timestamps y errores explícitos. `next_segment` es el índice del próximo segmento sin completar; un segmento puede tener varios lotes persistidos en `analysis/<id>/segment_<índice>/draft.json`.

`POST /api/jobs/<id>/retry` devuelve 202 para un trabajo `failed` o `pending_authorization`. No borra resultados confirmados. Un worker ocupado devuelve 409.

Estados: `queued`, `analyzing`, `exporting`, `generated_pending_review`, `needs_review`, `extracted_without_ai` (CLI), `failed`, `pending_authorization`.

## Entregas completas

No hay un único PPTX para toda duración: se divide en partes de hasta `DOCUMENT_STEPS_PER_VOLUME` pasos y se conserva el orden global. Leer todas las entradas de `deliveries` o `delivery/<id>/index.json`; cada entrada contiene `pptx`, `docx`, `first_step`, `last_step`. Son nombres de blobs privados, no URLs públicas. El cliente autorizado de Storage gestiona su descarga.

El procedimiento completo está en `analysis/<id>/procedure.json`: duración, segundos recorridos, cobertura por segmento, intervalo de capturas y todos los pasos. Las coordenadas `bbox` son proporciones de la imagen original. Un recuadro no demuestra un clic; las entregas permanecen pendientes de revisión.
