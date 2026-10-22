# Preparado para configurar en la otra laptop

1. Crear una `.venv` nueva e instalar `requirements.txt` con Python 3.11+.
2. Ejecutar `python scripts/configure.py` para crear archivos de configuración sin sobrescribir otros.
3. Completar `.env` con endpoint, clave y **nombre exacto del deployment existente de GPT-6.1 Sol**.
4. Ejecutar `python scripts/check_integrations.py` para verificar la conexión real.
5. Ejecutar `python run_real.py --video grabacion.mp4 --transcript grabacion.vtt` (también SRT/JSON).

MAI queda desactivado y pendiente de autorización. El procesamiento recorre toda la duración con checkpoints y produce PowerPoint con capturas, recuadros, flechas y textos editables. CLI y Azure Functions Flex Consumption comparten el motor.

Sin credenciales: `python run_real.py --video assets/video_demo_ficticio.mp4 --no-ai` valida extracción; no simula interpretación ni genera documentos con pasos inventados.

Ver [README_EJECUCION_REAL.md](README_EJECUCION_REAL.md) para configuración, Blob, despliegue, pruebas de 5 minutos/1 hora/5 horas y límites de lo verificado.
