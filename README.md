# Springtrap — voz conversacional 100% local

Animatrónico de Springtrap (FNAF 3) que escucha, piensa y responde en voz alta,
sin internet y sin servicios en la nube.

```
micrófono → Whisper (STT) → qwen3 4B en Ollama (LLM) → Piper (TTS) → altavoz
```

Todo corre en local. El LLM se queda cargado en la GPU entre turnos y la
respuesta se sintetiza **frase a frase mientras el modelo sigue generando**, así
que el primer audio sale mucho antes de que la respuesta esté completa.

## Estado actual

| Etapa | Motor | Latencia medida |
|---|---|---|
| STT | faster-whisper `small` float16 (GPU) | 0.2–0.6 s |
| LLM | `qwen3:4b-instruct-2507-q4_K_M` | 0.03–0.4 s al 1er token |
| TTS | Piper `es_ES-davefx-medium` | RTF 0.06 (~0.3 s por frase) |
| Total percibido | | **~0.5–0.7 s hasta el primer audio** |

Hardware de referencia: RTX 3050 6 GB, i5-12450HX, 16 GB RAM, **Windows 11**.
En uso simultáneo, LLM (3.2 GB) + STT en GPU (~0.5 GB) caben en los 6 GB.

## Arranque rápido (Windows)

```bat
C:\Animatronico\Springtrap.bat
```

Eso es todo: el `.bat` comprueba el venv, arranca Ollama si está caído, descarga
el modelo la primera vez y lanza la conversación. También acepta argumentos:

```bat
Springtrap.bat --texto               :: conversación por teclado
Springtrap.bat --mic-test            :: grabar una frase y ver qué transcribe
Springtrap.bat --selftest            :: valida STT-LLM-TTS sin micrófono
Springtrap.bat --benchmark           :: mide latencias reales
Springtrap.bat --list-devices        :: ver micrófonos y altavoces
Springtrap.bat --say "Hola"          :: probar solo la voz
```

### Instalación desde cero

```powershell
cd C:\Animatronico
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

> **La ruta del proyecto debe ser corta.** Piper 1.8.0 en Windows tiene un bug:
> espeak-ng guarda la ruta de sus datos en un búfer fijo y, si no cabe, la
> descarta y usa la de la máquina que compiló el wheel
> (`D:/a/piper1-gpl/...`). Con `C:\Animatronico` la ruta mide 60 caracteres y
> funciona; con `C:\Users\...\Documents\Universidad\7° Cuatrimestre\...` falla.
> Si ves `Error processing file 'D:/a/piper1-gpl/...phontab'`, es exactamente eso.

### Micrófono

`Mic` elige solo un dispositivo real: descarta el «Asignador de sonido
Microsoft», el «Controlador primario», «Mezcla estéreo» y Nahimic, y prefiere
WASAPI. En este portátil acaba en el **array interno** (`[9] Varios micrófonos
(Realtek(R) Audio)`), no en el `[1]` que Windows pone por defecto.

Para forzar otro (por ejemplo el micro de jack del concurso):

```bat
set SPRINGTRAP_MIC=10
set SPRINGTRAP_MIC=Mic input
```

Un índice o un trozo del nombre; lo que no se encuentre se ignora.

> El jack combo del portátil comparte entrada con auriculares. Al enchufar el
> micro, Windows pregunta qué has conectado: elige **Micrófono**. Si el nivel
> llega bajo, sube la ganancia en *Configuración → Sistema → Sonido → Entrada*.

Dentro de la conversación:

- `Enter` → empieza a escuchar y para solo al detectar silencio.
- Escribir texto + `Enter` → se lo dices por teclado (útil si el micro falla).
- `/reset` → olvida la conversación.
- `/salir` → termina.

> **Importante antes de una demo:** ejecuta `--selftest` una vez. La primera
> carga del modelo tras arrancar el equipo tarda ~30 s porque lo lee de disco;
> después son ~9 s. `llm.py` manda `keep_alive=30m` en cada petición, así que el
> modelo no se descarga de la VRAM entre turnos (ni pide configuración extra).
> Y antes de hablar, `--mic-test` te dice en 10 segundos si el micro capta.

## Cómo está montado

```
springtrap/
├── main.py                    # CLI: mic, texto, selftest, benchmark
├── Springtrap.bat             # lanzador de Windows
├── run.sh                     # lanzador antiguo de WSL (legado)
├── springtrap/
│   ├── __init__.py            # parche de PortAudio (sin sudo, solo Linux)
│   ├── bootstrap.py           # LD_LIBRARY_PATH en WSL / DLLs CUDA en Windows
│   ├── config.py              # todos los parámetros, por variables de entorno
│   ├── persona.py             # system prompt + frases de respaldo
│   ├── llm.py                 # cliente Ollama con streaming y memoria
│   ├── stt.py                 # faster-whisper
│   ├── tts.py                 # Piper + pitch shift
│   ├── audio.py               # micrófono con VAD + reproductor con colchón
│   └── pipeline.py            # orquestación y frases incrementales
├── scripts/
│   ├── start_ollama.sh        # Ollama con ajustes para 6 GB de VRAM (WSL)
│   └── download_voice.py      # descarga voces de Piper
├── voices/                    # modelos de voz .onnx
└── models/ollama/             # pesos de los modelos (solo WSL)
```

### Decisiones que importan

- **qwen3 4B y no un 7B.** El 7B en q4 ocupa 4.7 GB y no cabe en 6 GB: Ollama
  lo reparte y acaba 18 % en CPU, el doble de lento y con peor español en las
  pruebas. El 4B entra entero (3.2 GB) y deja VRAM libre.
- **Piper y no ElevenLabs.** ElevenLabs es cloud, de pago y depende del wifi del
  campus. Piper tarda 0.3 s por frase en CPU y no ocupa VRAM.
- **Respuestas de 1–2 frases.** No es solo estético: menos tokens = menos
  latencia y menos tiempo de síntesis. El prompt lo impone de forma explícita.
- **Colchón de 0,8 s y frases de ≥30 caracteres.** El streaming sintetiza por
  frases: si la primera dura menos que lo que tarda en llegar la segunda, el
  altavoz se queda sin datos y se oyen cortes. El reproductor no empieza a sonar
  hasta acumular 0,8 s (o hasta el `flush()` de fin de turno), y `SentenceStream`
  no manda trozos sueltos como «Vivo.» a Piper.
- **Pitch shift por remuestreo.** Bajar 2 semitonos añade aspereza metálica,
  que aquí suma carácter. También emborrona los formantes: para el STT se nota
  solo en audio sintético, no con voz humana.

## Ajustes (variables de entorno)

| Variable | Por defecto | Para qué |
|---|---|---|
| `SPRINGTRAP_LLM` | `qwen3:4b-instruct-2507-q4_K_M` | otro modelo de Ollama |
| `SPRINGTRAP_TEMP` | `0.85` | creatividad del personaje |
| `SPRINGTRAP_MAX_TOKENS` | `80` | longitud máxima (subirlo aumenta latencia) |
| `SPRINGTRAP_MAX_CHARS` | `190` | tope duro de caracteres (~32 palabras) por turno |
| `SPRINGTRAP_HISTORY` | `10` | turnos de memoria (bajarlo acorta el prompt) |
| `SPRINGTRAP_STT` | `small` | `base`, `small`, `medium`… |
| `SPRINGTRAP_STT_DEVICE` | `auto` | `auto`, `cuda` o `cpu` (con caída automática) |
| `SPRINGTRAP_VOICE` | `es_ES-davefx-medium` | voz de Piper |
| `SPRINGTRAP_PITCH` | `-2.0` | semitonos; `0` = voz natural, `-1.5` más natural |
| `SPRINGTRAP_PEAK` | `0.7` | pico de salida; bajarlo si satura el altavoz |
| `SPRINGTRAP_VAD_SILENCE` | `0.6` | silencio (s) para dejar de grabar |
| `SPRINGTRAP_VAD_MIN` | `0.012` | umbral mínimo de voz (súbelo con música de fondo) |
| `SPRINGTRAP_VAD_MULT` | `4.0` | cuántas veces el ruido de fondo debe superarse |
| `SPRINGTRAP_MIC` | *(auto)* | índice o trozo del nombre del micro de entrada |
| `SPRINGTRAP_OUTPUT` | *(defecto)* | índice de dispositivo de salida |
| `SPRINGTRAP_JAW` | `0` | `1` activa la mandíbula (SG90 en ESP32) |
| `SPRINGTRAP_JAW_PORT` | `/dev/ttyUSB0` | puerto serie; en Windows `COM5`, `COM6`… |
| `SPRINGTRAP_JAW_MIN` / `MAX` | `10` / `60` | ángulo cerrado / abierto |
| `SPRINGTRAP_JAW_FLOOR` / `CEIL` | `-45` / `-12` | dBFS de silencio / voz fuerte |
| `SPRINGTRAP_JAW_GAMMA` | `0.7` | curva de apertura |
| `SPRINGTRAP_JAW_ATTACK` / `RELEASE` | `0.6` / `0.15` | suavizado al abrir / cerrar |
| `SPRINGTRAP_JAW_SLEW` | `700` | grados por segundo máximos |
| `SPRINGTRAP_JAW_DEADBAND` | `2` | histéresis en grados |
| `SPRINGTRAP_JAW_HEARTBEAT` | `0.75` | s entre reenvíos del mismo ángulo |

Ejemplo:

```bat
set SPRINGTRAP_PITCH=-1.5
set SPRINGTRAP_VAD_MIN=0.025
Springtrap.bat
```

Otras voces en español:

```bat
.venv\Scripts\python.exe scripts\download_voice.py es_MX-claude-high
set SPRINGTRAP_VOICE=es_MX-claude-high
Springtrap.bat
```

## Mandíbula (SG90 + ESP32)

La mandíbula sigue el nivel de la voz: `Player` entrega el RMS cada 50 ms y
`springtrap/jaw.py` lo convierte en un ángulo que viaja por USB al ESP32.

- Firmware: `firmware/jaw_servo/jaw_servo.ino` (Arduino IDE, una sola vez).
- Pruebas y calibración: `scripts/jaw_test.py`.
- **Guía paso a paso (cableado, Arduino IDE, calibración):**
  [`docs/MANDIBULA.md`](docs/MANDIBULA.md).

```bat
set SPRINGTRAP_JAW=1
set SPRINGTRAP_JAW_PORT=COM5
Springtrap.bat
```

## Problemas conocidos

**`Error processing file 'D:/a/piper1-gpl/...phontab'`** — bug de Piper en
Windows por la longitud de la ruta. Mueve el proyecto a una ruta corta
(`C:\Animatronico`). No lo parchees con nombres 8.3: en otro equipo puede estar
desactivado.

**`No puedo hablar con Ollama`** — el servicio no está arrancado. En Windows,
abre Ollama desde el menú Inicio (o `Springtrap.bat`, que lo intenta solo).
En WSL, `./scripts/start_ollama.sh` en otra terminal.

**`El modelo ... no está descargado`** — `ollama pull qwen3:4b-instruct-2507-q4_K_M`.

**`Invalid sample rate` / el micro no abre** — `Mic` pide 16 kHz con
`WasapiSettings(auto_convert=True)` y, si el dispositivo no lo acepta, graba a
su frecuencia nativa y remuestrea con PyAV. Si aun así falla, prueba otro
índice con `SPRINGTRAP_MIC`.

**Whisper va en CPU** — faltan las DLLs de cuDNN/cuBLAS o `bootstrap.py` no las
registró. Comprueba con `Springtrap.bat --mic-test`: la línea `Whisper (cuda)` o
`Whisper (cpu)` lo dice. Reinstala con
`.venv\Scripts\python.exe -m pip install -r requirements.txt`.

**No hay dispositivos de audio en WSL** — el audio depende de WSLg. Comprueba
que `/mnt/wslg/PulseServer` existe. (Motivo del port a Windows: WSLg añadía
hasta 591 ms al abrir el micro y cortaba la reproducción.)

**El micro se oye a sí mismo** — el altavoz entra por el micro y el animatrónico
se responde a sí mismo. El flujo actual espera a que termine de hablar antes de
grabar, así que no debería pasar. Si pasa, acerca el micro a la boca y sepáralo
del altavoz.

**Transcribe mal** — sube a `SPRINGTRAP_STT=medium` (más lento) o revisa el
nivel con `--mic-test`. Con música alta de fondo, sube `SPRINGTRAP_VAD_MIN`.

## Siguientes pasos

1. **Mandíbula con servos.** ✅ Hecho: SG90 en ESP32 con firmware propio
   (`firmware/jaw_servo/`) y control desde Python (`springtrap/jaw.py`). Guía en
   [`docs/MANDIBULA.md`](docs/MANDIBULA.md).
2. **Cancelación de eco** para escucha continua sin pulsar Enter (AEC de Speex
   o un array ReSpeaker con AEC por hardware).
3. **Wake word** («Springtrap») con `openWakeWord`, en lugar del botón.
4. **RAG del proyecto**: un `.txt` con la ficha del animatrónico para que
   responda a «¿cómo te han construido?».
5. **RVC** si se quiere clonar la voz exacta del juego (requiere GPU y un
   dataset de clips).
