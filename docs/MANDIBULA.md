# Mandíbula con SG90 + ESP32 (paso a paso)

Esta guía monta la mandíbula de Springtrap: un servo **SG90** movido por un
**ESP32**, sincronizado con la voz que reproduce la PC.

La idea es sencilla:

```
voz (Python)  ->  RMS cada 50 ms  ->  ángulo (Python)  ->  USB serie  ->  ESP32  ->  SG90
```

- **El ESP32 es solo el músculo.** Recibe un ángulo y mueve el servo.
- **Toda la lógica vive en Python**, en `springtrap/jaw.py`: ritmo, suavizado y
  calibración. Ahí se ajusta todo sin volver a flashear.
- **Arduino IDE se usa una sola vez**, para grabar el sketch. Después no lo
  vuelves a abrir para la demo.

---

## 0. Materiales

| Pieza | Nota |
|---|---|
| ESP32 (Dev Module o similar) | cualquiera con USB |
| SG90 | servo micro 9 g |
| Fuente 5 V ≥ 1 A | **externa**, no el pin 5V del ESP32 |
| Condensador 470–1000 µF | entre 5 V y GND, cerca del servo |
| Cables dupont | señal, GND y alimentación |
| Mecanismo de mandíbula | palanca, hilo, varilla… lo que uses |

---

## 1. Cableado

| SG90 | Va a |
|---|---|
| Marrón o negro (GND) | GND del ESP32 **y** GND de la fuente |
| Rojo (VCC) | **+5 V de la fuente externa** |
| Naranja (señal) | **GPIO 13** del ESP32 |

```
Fuente 5V + ----+---- rojo SG90
                |
              470-1000 uF
                |
Fuente 5V - ----+---- marron SG90 ---- GND ESP32
                                     |
                         naranja ---- GPIO 13
```

> **Importante**
> - **No alimentes el SG90 desde el pin 5V del ESP32.** Los picos del servo
>   (~650 mA) reinician la placa y se cae el puerto serie.
> - **Une siempre el GND de la fuente con el GND del ESP32.** Sin referencia
>   común la señal PWM no funciona.
> - El condensador evita que el arranque del servo baje la tensión y reinicie
>   el ESP32.

### Límites mecánicos

El SG90 gira 180°, pero la mandíbula no debe usarlos todos. En el sketch:

```cpp
const int ANGLE_MIN = 10;   // cerrada
const int ANGLE_MAX = 60;   // abierta
```

Ajusta esos números a tu montaje **antes de atornillar nada**: si el servo
empuja contra un tope, zumba, se calienta y puede romper el engranaje.

---

## 2. Instalar Arduino IDE

1. Descarga Arduino IDE 2.x desde <https://www.arduino.cc/en/software>.
2. Instálalo con las opciones por defecto.

### 2.1 Añadir la placa ESP32

1. Abre **File → Preferences** (Archivo → Preferencias).
2. En *Additional boards manager URLs* pega:

   ```
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
   ```

3. Ve a **Tools → Board → Boards Manager** (Herramientas → Placa → Gestor de
   placas), busca **esp32** e instala **esp32 by Espressif Systems**.

### 2.2 Instalar la librería del servo

1. **Sketch → Include Library → Manage Libraries**
   (Programa → Incluir librería → Gestionar librerías).
2. Busca **ESP32Servo** e instala la de **Kevin Harrington / John K. Bennett**.

> No uses la librería `Servo.h` clásica de Arduino: en ESP32 hay que usar
> `ESP32Servo`.

---

## 3. Grabar el firmware (una sola vez)

1. Conecta el ESP32 por USB.
2. Abre el archivo:

   ```
   firmware/jaw_servo/jaw_servo.ino
   ```

3. Configura en **Tools**:
   - **Board:** `ESP32 Dev Module` (o tu placa exacta).
   - **Port:** el puerto del ESP32 (en Windows `COM5`, `COM6`…).
   - Si al subir da error, mantén pulsado **BOOT** durante la subida.
4. Pulsa **Upload** (flecha →).

### Comprobar que quedó bien

1. Abre **Tools → Serial Monitor**.
2. Pon **115200 baudios**.
3. Pulsa **EN** (reset) en la placa: debe aparecer

   ```
   READY
   ```

4. Escribe `10` y Enter → mandíbula cerrada.
5. Escribe `60` y Enter → mandíbula abierta.

Si esto funciona, **el hardware y el firmware están listos**. Cierra el Serial
Monitor antes de usar Python: el puerto solo lo puede abrir un programa a la vez.

---

## 4. Preparar Python

Desde la raíz del proyecto:

```bat
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Esto instala `pyserial` (ya está en `requirements.txt`).

### Averiguar el puerto

- **Windows:** Administrador de dispositivos → *Puertos (COM y LPT)*. Suele ser
  `COM5` o `COM6`.
- **Linux:** `/dev/ttyUSB0` o `/dev/ttyACM0`.
- **macOS:** `/dev/cu.usbserial-*`.

### Variables de entorno

```bat
set SPRINGTRAP_JAW=1
set SPRINGTRAP_JAW_PORT=COM5
set SPRINGTRAP_JAW_MIN=10
set SPRINGTRAP_JAW_MAX=60
Springtrap.bat
```

También puedes dejarlas fijas en `Springtrap.bat`. **Ya vienen activadas**
para `COM6`; si cambias de puerto USB, edita esas cuatro líneas en el `.bat`.

---

## 5. Probar sin voz

Con el ESP32 conectado y el Serial Monitor cerrado:

```bat
.venv\Scripts\python.exe scripts\jaw_test.py sweep --port COM5
```

La mandíbula debe abrir y cerrar despacio, sin golpear los topes.

Prueba también el mapeo de niveles (no necesita audio):

```bat
.venv\Scripts\python.exe scripts\jaw_test.py level --port COM5
```

Verás en pantalla los ángulos que se envían mientras se simula una voz.

---

## 6. Probar con voz real

```bat
.venv\Scripts\python.exe scripts\jaw_test.py talk --port COM5
```

Sintetiza una frase con Piper y mueve la mandíbula con el audio real. Si abre
poco, se queda abierta o tiembla, ajusta en el paso 7.

---

## 7. Calibración

Todas estas variables se pueden poner como variables de entorno o editar en
`springtrap/config.py`:

| Variable | Por defecto | Qué hace |
|---|---|---|
| `SPRINGTRAP_JAW_MIN` | `10` | ángulo cerrado |
| `SPRINGTRAP_JAW_MAX` | `60` | ángulo abierto |
| `SPRINGTRAP_JAW_FLOOR` | `-45` | dBFS que cuenta como silencio |
| `SPRINGTRAP_JAW_CEIL` | `-12` | dBFS que cuenta como voz fuerte |
| `SPRINGTRAP_JAW_GAMMA` | `0.7` | <1 abre más en niveles medios; >1 abre menos |
| `SPRINGTRAP_JAW_ATTACK` | `0.6` | rapidez al abrir (0–1) |
| `SPRINGTRAP_JAW_RELEASE` | `0.15` | rapidez al cerrar (0–1) |
| `SPRINGTRAP_JAW_SLEW` | `700` | grados por segundo máximos |
| `SPRINGTRAP_JAW_DEADBAND` | `2` | grados de histéresis (subir si zumba) |
| `SPRINGTRAP_JAW_HEARTBEAT` | `0.75` | s entre reenvíos del mismo ángulo |

### Diagnóstico rápido

| Síntoma | Ajuste |
|---|---|
| Abre muy poco | baja `JAW_CEIL` (p. ej. `-18`) o sube `JAW_GAMMA` |
| Se queda abierta en silencio | sube `JAW_FLOOR` (p. ej. `-35`) |
| Abre y cierra a golpes | baja `JAW_ATTACK` a `0.4` y `JAW_SLEW` a `400` |
| Tiembla quieta | sube `JAW_DEADBAND` a `3`–`4` |
| Va al revés | pon `const bool INVERT = true;` en el `.ino` y vuelve a subir |
| Se mueve entre frases | sube `JAW_RELEASE` a `0.25` |

`JAW_RELEASE` bajo es lo que evita que la boca “castañetee” cuando el
reproductor manda un nivel 0 entre frase y frase.

---

## 8. Prueba final con Springtrap

```bat
set SPRINGTRAP_JAW=1
set SPRINGTRAP_JAW_PORT=COM5
Springtrap.bat
```

Pregúntale su historia y la mandíbula debe acompañar la voz.

Al arrancar verás:

```
Mandíbula lista en COM5
```

Si aparece `Mandíbula desactivada: ...`, el mensaje dice el motivo (puerto
ocupado, `pyserial` ausente, nombre de COM incorrecto…).

---

## 9. Cómo funciona por dentro

1. `Player` reproduce el audio en bloques de **50 ms** y llama a `on_level(rms)`.
2. `Jaw.update(rms)` convierte el RMS a **dBFS**:
   `20·log10(rms)`.
3. Lo normaliza entre `JAW_FLOOR` y `JAW_CEIL`, le aplica `gamma` y lo mapea a
   grados entre `JAW_MIN` y `JAW_MAX`.
4. Suaviza con **ataque rápido / liberación lenta**, limita la velocidad
   (`slew`) y aplica una **zona muerta**.
5. Envía `"37\n"` por el puerto serie. El ESP32 recorta el ángulo a su rango
   seguro y mueve el servo.
6. Si el ESP32 deja de recibir durante **2 s** (watchdog del firmware), cierra
   la mandíbula solo. Así nunca se queda abierta si se cae Python o el USB.

---

## 10. Problemas frecuentes

**`could not open port 'COM5'`**
El puerto está ocupado (Serial Monitor de Arduino) o es otro COM. Ciérralo y
revisa el Administrador de dispositivos.

**`Permission denied: '/dev/ttyUSB0'` (Linux)**
Añade tu usuario al grupo `dialout` y vuelve a iniciar sesión:
`sudo usermod -aG dialout $USER`.

**El servo zumba y no se mueve**
Fuente insuficiente o GND sin unir. Revisa el cableado y el condensador.

**El ESP32 se reinicia al mover el servo**
Estás alimentando el servo desde el ESP32. Usa la fuente externa.

**El servo se mueve pero al revés**
`INVERT = true` en el `.ino`, vuelve a subir y listo.

**Todo funciona pero la boca no sigue bien las sílabas**
Baja `SPRINGTRAP_JAW_ATTACK` a `0.4`, sube `SPRINGTRAP_JAW_CEIL` un poco y
prueba `JAW_GAMMA` entre `0.5` y `0.9`.
