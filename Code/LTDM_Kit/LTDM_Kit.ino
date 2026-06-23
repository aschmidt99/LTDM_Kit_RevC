/* This code creates precisely timed pulses for sustaining vibrations of a resonant system, like Figure 2 of Paul Vo's Patent: [https://patents.google.com/patent/EP1218716B1](https://patents.google.com/patent/EP1218716B1)

For Teensy 4.1 with RevB (black) PCB plugged into the UI PCB (RevA)

To do:
- Reinstate Noisy initation/onset
- Reinstate target RMS
- Map faders to harmonics????
*/

#include "imxrt.h"
#include "core_pins.h"
#include "debug/printf.h"
#include <Arduino.h>
#include <SPI.h>
#include "SineTable.h"
#include "Adafruit_TLC5947.h"
#include "Servo.h"

#include "pinmap.h"
#include "debug.h"
#include "flexpwm.h"
#include "ui.h"
#include "system_config.h"
#include "harmonics.h"
#include "context.h"
#include "render.h"
#include "serialctrl.h"

void setup() {
  delay(2000);
  Serial.begin(115200);
  analogReadResolution(12);  // default should be 12
  analogReadAveraging(0);     // Disable averaging (set to 0) for faster reading... 3 seems to be fine, but 4 is far too much
  initUI();           // initialize the UI (delcare pins f)
  initServo();
  initFlexPWM();
  pinMode(GPIO_PIN, OUTPUT);
  renderSetup(&context);
  setInterrupts();
  initSineTable();
}

void loop() {
  pollSerialControl();
  output();
}