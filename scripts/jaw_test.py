"""Pruebas y calibración de la mandíbula (SG90 + ESP32).

Uso (desde la raíz del proyecto, con el ESP32 conectado)::

    python scripts/jaw_test.py sweep --port COM5
    python scripts/jaw_test.py sweep --port COM5 --min 10 --max 60
    python scripts/jaw_test.py level --port COM5
    python scripts/jaw_test.py talk  --port COM5 --text "Hola, soy Springtrap"

``sweep``  mueve la mandíbula despacio por todo el rango (comprueba el montaje).
``level``  simula una voz y muestra en pantalla los ángulos que enviaría.
``talk``   sintetiza una frase con Piper y mueve la mandíbula con el audio real.

Necesita ``pyserial`` instalado en el entorno (``pip install -r requirements.txt``).
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from pathlib import Path

# Permite ejecutar el script desde scripts/ sin instalar el paquete.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from springtrap import config  # noqa: E402
from springtrap.jaw import Jaw  # noqa: E402


def _jaw(args: argparse.Namespace) -> Jaw:
    return Jaw(
        port=args.port or config.JAW_PORT,
        baudrate=args.baud or config.JAW_BAUDRATE,
        min_angle=args.min if args.min is not None else config.JAW_MIN_ANGLE,
        max_angle=args.max if args.max is not None else config.JAW_MAX_ANGLE,
    )


def cmd_sweep(args: argparse.Namespace) -> None:
    jaw = _jaw(args)
    angle_min, angle_max = int(jaw.min_angle), int(jaw.max_angle)
    step_ms = args.step_ms
    print(f"Barrido {angle_min}° -> {angle_max}° -> {angle_min}°  ({args.cycles} ciclos)")
    print("Mira la mandíbula: debe abrir y cerrar sin forzar los topes.")
    try:
        for _ in range(args.cycles):
            for angle in range(angle_min, angle_max + 1, 2):
                jaw.move_to(angle)
                time.sleep(step_ms / 1000.0)
            for angle in range(angle_max, angle_min - 1, -2):
                jaw.move_to(angle)
                time.sleep(step_ms / 1000.0)
    except KeyboardInterrupt:
        pass
    finally:
        jaw.close()
    print("Listo. Si el recorrido es corto o zumba, ajusta ANGLE_MIN/MAX en el .ino.")


def cmd_level(args: argparse.Namespace) -> None:
    jaw = _jaw(args)
    print("Simulación de voz: 3 s de silencio, 6 s modulando y 2 s de silencio.")
    print("Ángulo | nivel")
    t0 = time.perf_counter()
    try:
        while True:
            t = time.perf_counter() - t0
            if t > 11.0:
                break
            if 3.0 <= t <= 9.0:
                # Envolvente tipo sílabas: 4 Hz de modulación + ruido suave.
                envelope = 0.5 + 0.5 * math.sin(2 * math.pi * 4.0 * (t - 3.0))
                rms = 0.004 + 0.09 * envelope
            else:
                rms = 0.0
            jaw.update(rms)
            angle = int(round(jaw.angle))
            bar = "#" * max(0, (angle - int(jaw.min_angle)))
            print(f"  {angle:3d}°  | {bar:<50}", end="\r")
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        jaw.close()
        print()


def cmd_talk(args: argparse.Namespace) -> None:
    from springtrap.audio import Player
    from springtrap.pipeline import SentenceStream
    from springtrap.tts import Voice

    jaw = _jaw(args)
    voice = Voice()
    print("Cargando Piper...")
    voice.load()

    player = Player(
        samplerate=voice.sample_rate or 22050,
        on_level=jaw.update,
    )
    player.start()
    text = args.text
    print(f"Diciendo: {text}")
    try:
        for sentence in SentenceStream().feed(text + " ") or [text]:
            player.play(voice.synthesize(sentence))
        player.wait()
    finally:
        player.close()
        jaw.close()
    print("Listo. Ajusta FLOOR/CEIL/GAMMA si abre poco o se queda abierta.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba y calibración de la mandíbula.")
    parser.add_argument("mode", choices=("sweep", "level", "talk"))
    parser.add_argument("--port", help="Puerto serie (p. ej. COM5 o /dev/ttyUSB0).")
    parser.add_argument("--baud", type=int, help="Baudios (por defecto 115200).")
    parser.add_argument("--min", type=int, help="Ángulo cerrado.")
    parser.add_argument("--max", type=int, help="Ángulo abierto.")
    parser.add_argument("--cycles", type=int, default=2, help="Ciclos del barrido.")
    parser.add_argument("--step-ms", type=int, default=25, help="Pausa por paso del barrido.")
    parser.add_argument(
        "--text",
        default="Hola. Soy Springtrap. Dicen que me están arreglando unos estudiantes de la UPEGRO.",
        help="Frase para el modo talk.",
    )
    args = parser.parse_args()

    {"sweep": cmd_sweep, "level": cmd_level, "talk": cmd_talk}[args.mode](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
