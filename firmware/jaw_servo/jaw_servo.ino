/*
 * jaw_servo.ino — Mandíbula de Springtrap (SG90) controlada por USB serie.
 *
 * El ESP32 es solo el músculo: recibe un ángulo entero por el puerto serie y
 * mueve el servo. Toda la lógica de voz (RMS, suavizado, calibración) vive en
 * Python, en la PC (springtrap/jaw.py).
 *
 * Protocolo (115200 baudios, una línea por comando):
 *   PC  -> ESP32 : "37\n"   ángulo en grados (se recorta al rango seguro)
 *   ESP32 -> PC  : "READY\n" al arrancar
 *
 * Seguridad:
 *   - El ángulo se recorta siempre a [ANGLE_MIN, ANGLE_MAX].
 *   - Watchdog: si pasan WATCHDOG_MS sin recibir nada, la mandíbula se cierra.
 *
 * Placa: "ESP32 Dev Module" (o la que corresponda).
 * Librería: ESP32Servo (Gestor de librerías de Arduino IDE).
 */

#include <ESP32Servo.h>

// ---------------------------------------------------------------- ajustes ---
const int SERVO_PIN = 13;        // GPIO de la señal naranja del SG90
const int ANGLE_MIN = 10;        // mandíbula cerrada (ajusta con el montaje)
const int ANGLE_MAX = 60;        // mandíbula abierta  (no pases de ~60)
const unsigned long WATCHDOG_MS = 2000;

// Si el servo gira al revés respecto a la boca, pon esto en true y vuelve a
// subir el sketch. Así el ángulo cerrado sigue siendo ANGLE_MIN.
const bool INVERT = false;

// Anchura de pulso del SG90. Si el servo zumba o pierde recorrido, prueba
// 500-2400 (habitual) o 600-2400.
const int PULSE_MIN_US = 500;
const int PULSE_MAX_US = 2400;

// ----------------------------------------------------------------- estado ---
Servo jaw;
int currentAngle = ANGLE_MIN;
unsigned long lastCommandAt = 0;
String line = "";

// ---------------------------------------------------------------- helpers ---
int clampAngle(int angle) {
  if (angle < ANGLE_MIN) return ANGLE_MIN;
  if (angle > ANGLE_MAX) return ANGLE_MAX;
  return angle;
}

void moveTo(int angle) {
  angle = clampAngle(angle);
  if (angle == currentAngle) return;  // evita zumbido por comandos repetidos

  currentAngle = angle;
  int physical = INVERT ? (ANGLE_MIN + ANGLE_MAX - angle) : angle;
  jaw.write(physical);
}

void setup() {
  Serial.begin(115200);

  jaw.attach(SERVO_PIN, PULSE_MIN_US, PULSE_MAX_US);
  jaw.write(INVERT ? ANGLE_MAX : ANGLE_MIN);  // arranca cerrada
  delay(300);

  Serial.println("READY");
}

void loop() {
  // Lectura no bloqueante, línea a línea.
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\n' || c == '\r') {
      if (line.length() > 0) {
        int angle = line.toInt();
        moveTo(angle);
        lastCommandAt = millis();
      }
      line = "";
    } else if ((c >= '0' && c <= '9') || c == '-') {
      if (line.length() < 8) line += c;  // ignora basura / líneas gigantes
    } else {
      line = "";  // carácter inesperado: descarta la línea
    }
  }

  // Watchdog: sin datos durante WATCHDOG_MS -> cierra la boca.
  if (lastCommandAt != 0 && millis() - lastCommandAt > WATCHDOG_MS) {
    moveTo(ANGLE_MIN);
    lastCommandAt = millis();
  }
}
