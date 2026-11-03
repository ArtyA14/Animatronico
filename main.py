#!/usr/bin/env python3
"""Springtrap: consola de voz local.

Uso:
    python main.py                  # conversación por micrófono
    python main.py --texto          # conversación escribiendo (sin mic)
    python main.py --say "Hola"     # solo prueba la voz
    python main.py --mic-test       # grabar y transcribir una frase
    python main.py --benchmark      # mide latencias reales
    python main.py --list-devices   # ver micrófonos y altavoces
"""

from __future__ import annotations

import argparse
import sys
import time

# Sin PYTHONUTF8 la consola de Windows usa cp1252 y un «→» tumba el programa al
# imprimir. Preferimos un «?» a un traceback en mitad de una demo.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from springtrap.bootstrap import ensure_native_libs

ensure_native_libs()  # reejecuta con LD_LIBRARY_PATH si hace falta

import springtrap  # noqa: E402  (parchea PortAudio antes de sounddevice)
from springtrap import config, persona
from springtrap.audio import Mic
from springtrap.llm import Brain
from springtrap.pipeline import Springtrap
from springtrap.stt import Transcriber
from springtrap.tts import Voice

console = Console()


def build(args) -> Springtrap:
    brain = Brain(model=args.model)
    transcriber = Transcriber(model_size=args.stt)
    voice = Voice(key=args.voice)
    mic = Mic(device=args.mic)
    return Springtrap(brain=brain, transcriber=transcriber, voice=voice, mic=mic)


def cmd_mic_test(app: Springtrap) -> None:
    """Grabación real de prueba: dispositivo, nivel y transcripción.

    Sirve para el día del concurso: si el micro no capta (jack mal elegido,
    ganancia a cero) se ve en 10 segundos sin arrancar el LLM ni Piper.
    """
    import numpy as np

    mic = app.mic
    console.print(f"[bold]Micrófono:[/bold] {mic.describe()}")
    info = mic.check()
    console.print(
        f"[dim]canales {info['channels']} · {int(info['samplerate'])} Hz nativo · "
        f"{info['hostapi']} · pedimos {mic.samplerate} Hz[/dim]"
    )

    input("Pulsa Enter y habla (di algo como «hola, prueba de micrófono»)... ")

    # Sonda cruda: separa «no has hablado» de «el micro no entrega señal».
    probe = mic.probe(1.5)
    probe_peak = float(np.max(np.abs(probe))) if probe.size else 0.0
    probe_rms = float(np.sqrt(np.mean(probe * probe))) if probe.size else 0.0
    console.print(f"[dim]Nivel de entrada: RMS {probe_rms:.5f} · pico {probe_peak:.5f}[/dim]")

    if probe_peak < 5e-4:
        console.print(
            "[red]El micrófono entrega un nivel casi nulo "
            f"({probe_peak:.6f} de pico, unas {-20 * np.log10(max(probe_peak, 1e-9)):.0f} dBFS).[/red]"
            " No es el código: no hay señal que capturar.\n"
            "  1. Mira si el portátil tiene una tecla de silencio de micro "
            "(Fn + la tecla con el icono de micrófono).\n"
            "  2. Configuración → Sistema → Sonido → Entrada: habla y comprueba "
            "que la barra se mueve.\n"
            "  3. Privacidad y seguridad → Micrófono: «Permitir que las "
            "aplicaciones de escritorio accedan».\n"
            "  4. Si nada de eso, prueba el micro de jack con "
            "SPRINGTRAP_MIC=Mic input"
        )
        return

    if probe_peak < 0.01:
        console.print(
            "[yellow]Nivel bajo:[/yellow] el micro capta, pero flojo. Sube la "
            "ganancia en Sonido → Entrada o acerca el micro a la boca."
        )

    started = time.perf_counter()
    audio = mic.record(silence_s=1.0, max_s=10.0, start_timeout_s=8.0)
    elapsed = time.perf_counter() - started

    if audio is None or not audio.size:
        console.print(
            "[red]No se detectó voz.[/red] Sube la ganancia del micro o baja el "
            "umbral con SPRINGTRAP_VAD_MIN=0.006"
        )
        return

    rms = float(np.sqrt(np.mean(audio * audio)))
    peak = float(np.max(np.abs(audio)))
    duration = audio.size / mic.samplerate
    console.print(
        f"[green]Capturado:[/green] {duration:.2f}s a {mic.samplerate} Hz "
        f"({elapsed:.2f}s reales) · RMS {rms:.4f} · pico {peak:.3f}"
    )
    if peak < 0.05:
        console.print("[yellow]Nivel muy bajo: activa «Mic Boost» o acerca el micro.[/yellow]")

    app.transcriber.load()
    heard = app.transcriber.transcribe(audio)
    console.print(f"[cyan]Whisper ({app.transcriber.device}):[/cyan] {heard or '(nada)'}")
    app.close()


def cmd_list_devices() -> None:
    import sounddevice as sd

    if springtrap.PORTAUDIO_PATH:
        console.print(f"[dim]PortAudio:[/dim] {springtrap.PORTAUDIO_PATH}")
    else:
        console.print(f"[dim]PortAudio:[/dim] {sd.get_portaudio_version()[1].splitlines()[0]}")
    table = Table(title="Dispositivos de audio")
    table.add_column("#", justify="right")
    table.add_column("Nombre")
    table.add_column("Host API", justify="right")
    table.add_column("Entradas", justify="right")
    table.add_column("Salidas", justify="right")
    table.add_column("SR", justify="right")
    for index, device in enumerate(sd.query_devices()):
        table.add_row(
            str(index),
            device["name"],
            sd.query_hostapis(device["hostapi"])["name"].replace("Windows ", ""),
            str(device["max_input_channels"]),
            str(device["max_output_channels"]),
            f"{int(device['default_samplerate'])}",
        )
    console.print(table)
    console.print(f"[dim]Entrada por defecto:[/dim] {sd.default.device[0]}")
    console.print(f"[dim]Salida por defecto:[/dim] {sd.default.device[1]}")
    console.print(f"[green]Micrófono elegido:[/green] {Mic().describe()}")


def cmd_say(app: Springtrap, text: str) -> None:
    app.voice.load()
    from springtrap.audio import Player

    app.player = Player(samplerate=app.voice.sample_rate)
    app.player.start()
    app.say(text)
    app.close()


def cmd_benchmark(app: Springtrap) -> None:
    questions = [
        "¿Quién eres?",
        "¿Qué pasó con los niños de Fazbear?",
        "¿Me ayudas con mi tarea de cálculo?",
    ]

    app.voice.load()
    app.transcriber.load()
    from springtrap.audio import Player

    app.player = Player(samplerate=app.voice.sample_rate)
    app.player.start()

    load_s = app.brain.warmup()
    console.print(f"[green]Modelo {app.brain.model} cargado en {load_s:.1f}s[/green]\n")

    rows = []
    for question in questions:
        app.brain.reset()
        t0 = time.perf_counter()
        first = None
        reply = ""
        for chunk in app.brain.stream_reply(question):
            if first is None:
                first = time.perf_counter() - t0
            reply += chunk
        total = time.perf_counter() - t0
        rows.append((question, reply, first or 0, total))

    table = Table(title="LLM")
    table.add_column("Pregunta")
    table.add_column("1er token", justify="right")
    table.add_column("Total", justify="right")
    for question, reply, first, total in rows:
        table.add_row(question, f"{first:.2f}s", f"{total:.2f}s")
        console.print(f"[green]Springtrap:[/green] {reply}")
    console.print(table)

    # TTS: caracteres por segundo de audio generado (RTF)
    sample = "Treinta años en este traje y todavía te sorprendes de verme hablar."
    t0 = time.perf_counter()
    audio = app.voice.synthesize(sample)
    elapsed = time.perf_counter() - t0
    duration = len(audio) / (app.voice.sample_rate or 22050)
    console.print(
        f"[bold]TTS:[/bold] {elapsed:.2f}s para {duration:.2f}s de audio "
        f"(RTF {elapsed / duration:.2f})"
    )

    # Round-trip TTS -> STT para validar la cadena completa
    heard = app.transcriber.transcribe(audio)
    console.print(f"[bold]STT escucha:[/bold] {heard} ({app.transcriber.last_duration:.2f}s)")

    app.close()


def cmd_selftest(app: Springtrap) -> None:
    """Valida STT -> LLM -> TTS sin micrófono.

    La pregunta se sintetiza con una voz neutra (sin pitch), porque Whisper
    se confunde con la voz artificial grave y el resultado no sería
    representativo de una persona real hablando.
    """
    app.warmup()

    neutral = Voice(pitch_semitones=0.0)
    neutral.load()
    question = "¿Quién eres y por qué hueles tan mal?"
    heard = app.transcriber.transcribe(neutral.synthesize(question))
    app.last_latency.stt_s = app.transcriber.last_duration

    console.print(f"\n[cyan]Pregunta:[/cyan] {question}")
    console.print(f"[cyan]STT:[/cyan] {heard}")
    reply = app.respond(heard)
    console.print(f"[green]Springtrap:[/green] {reply}")
    console.print(f"[dim]{app.last_latency.summary()}[/dim]")
    app.close()


def cmd_mic_loop(app: Springtrap) -> None:
    app.warmup()
    console.print(
        Panel(
            "[bold]Pulsa Enter para hablar[/bold] (o escribe para teclear la frase).\n"
            "[dim]/reset para olvidar la conversación · /salir para terminar[/dim]",
            title="Springtrap",
            border_style="green",
        )
    )
    app.say(persona.greeting())

    while True:
        try:
            line = input("\n[Enter] > ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if line.startswith("/"):
            if line in {"/salir", "/exit", "/quit"}:
                break
            if line == "/reset":
                app.brain.reset()
                console.print("[dim]Memoria borrada.[/dim]")
                continue
            console.print("[dim]Comandos: /reset, /salir[/dim]")
            continue

        if line:
            console.print(f"[cyan]Tú:[/cyan] {line}")
            reply = app.respond(line)
            if reply:
                console.print(f"[green]Springtrap:[/green] {reply}")
                console.print(f"[dim]{app.last_latency.summary()}[/dim]")
            continue

        console.print("[dim]Escuchando...[/dim]")
        heard = app.listen()
        if heard is None:
            console.print("[dim]No he oído nada.[/dim]")
            continue
        console.print(f"[cyan]Tú:[/cyan] {heard}")
        reply = app.respond(heard)
        if reply:
            console.print(f"[green]Springtrap:[/green] {reply}")
            console.print(f"[dim]{app.last_latency.summary()}[/dim]")

    app.say(persona.farewell())
    app.close()


def cmd_text_loop(app: Springtrap) -> None:
    app.warmup()
    console.print("[dim]Modo texto. /reset · /salir[/dim]")
    while True:
        try:
            line = input("\nTú > ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in {"/salir", "/exit", "/quit"}:
            break
        if line == "/reset":
            app.brain.reset()
            console.print("[dim]Memoria borrada.[/dim]")
            continue
        reply = app.respond(line)
        console.print(f"[green]Springtrap:[/green] {reply}")
        console.print(f"[dim]{app.last_latency.summary()}[/dim]")
    app.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Springtrap - voz local")
    parser.add_argument("--texto", action="store_true", help="conversar por teclado")
    parser.add_argument("--say", metavar="TEXTO", help="decir un texto y salir")
    parser.add_argument("--benchmark", action="store_true", help="medir latencias")
    parser.add_argument("--selftest", action="store_true", help="probar STT-LLM-TTS sin micrófono")
    parser.add_argument("--mic-test", action="store_true", help="grabar y transcribir una frase del micrófono")
    parser.add_argument("--list-devices", action="store_true", help="listar audio")
    parser.add_argument("--model", default=config.LLM_MODEL, help="modelo de Ollama")
    parser.add_argument("--stt", default=config.STT_MODEL, help="tamaño de Whisper")
    parser.add_argument("--voice", default=config.VOICE_KEY, help="voz de Piper")
    parser.add_argument("--mic", default=config.MIC_DEVICE, help="dispositivo de entrada")
    args = parser.parse_args()

    if args.list_devices:
        cmd_list_devices()
        return 0

    app = build(args)
    if args.say:
        cmd_say(app, args.say)
    elif args.benchmark:
        cmd_benchmark(app)
    elif args.selftest:
        cmd_selftest(app)
    elif args.mic_test:
        cmd_mic_test(app)
    elif args.texto:
        cmd_text_loop(app)
    else:
        cmd_mic_loop(app)
    return 0


if __name__ == "__main__":
    sys.exit(main())
