"""Local execution of exactly the Functions worker engine."""
import argparse
import json
from real_pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(description='Video completo → procedimiento editable')
    parser.add_argument('--video')
    parser.add_argument('--transcript', help='VTT, SRT o JSON con tiempos absolutos')
    parser.add_argument('--speaker', default='')
    parser.add_argument('--rules', default='')
    parser.add_argument('--segment-seconds', type=int)
    parser.add_argument('--frame-every-seconds', type=int)
    parser.add_argument('--resume', help='ID del trabajo existente; reintenta la unidad fallida')
    parser.add_argument('--no-ai', action='store_true', help='Extracción real sin análisis ni resultados IA simulados')
    args = parser.parse_args()
    if not args.video and not args.resume:
        parser.error('Se requiere --video o --resume')
    result = run_pipeline(args.video, args.transcript, args.speaker, args.rules, not args.no_ai,
                          resume=args.resume, segment_seconds=args.segment_seconds,
                          frame_every_seconds=args.frame_every_seconds)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result['status'] in ('failed', 'pending_authorization', 'busy') else 0


if __name__ == '__main__':
    raise SystemExit(main())
