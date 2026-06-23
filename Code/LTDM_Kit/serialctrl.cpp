// serialctrl.cpp
#include "serialctrl.h"
#include "ui.h"          // sliderStates[], buttonStates[], pedalStates[]

// Protocol constants
static const uint8_t START_MARKER = 255;
static const uint8_t END_MARKER   = 254;
static const uint8_t FULLSCALE    = 128;  // max data byte -> stays clear of markers

// payload = 1 mode + 16 sliders + 16 buttons + 2 pedals
static const uint8_t PAYLOAD_LEN  = 1 + 16 + 16 + 2;   // 35
static const uint8_t BUF_LEN      = 48;                // a little headroom

// Clamp applied slider values just under 1.0.
static const float SLIDER_MAX = 0.999f;

// Receive state machine
volatile bool serialOverride = false;

static uint8_t  rxBuf[BUF_LEN];
static uint8_t  rxIdx   = 0;
static bool     inFrame = false;
static uint32_t lastFrameMs = 0;

static void applyFrame(const uint8_t *p, uint8_t len) {
  if (len < PAYLOAD_LEN) return;            // short/incorrect/noisy frame -> ignore
  const bool wantOverride = (p[0] != 0);

  // Apply atomically with respect to the sense ISR (which reads these arrays).
  noInterrupts();
  serialOverride = wantOverride;
  if (wantOverride) {
    for (int i = 0; i < 16; i++) {
      float s = (float)p[1 + i] / (float)FULLSCALE;
      if (s > SLIDER_MAX) s = SLIDER_MAX;
      sliderStates[i] = s;
      buttonStates[i] = (p[17 + i] != 0);
    }
    float p0 = (float)p[33] / (float)FULLSCALE;
    float p1 = (float)p[34] / (float)FULLSCALE;
    pedalStates[0] = (p0 > SLIDER_MAX) ? SLIDER_MAX : p0;
    pedalStates[1] = (p1 > SLIDER_MAX) ? SLIDER_MAX : p1;
  }
  interrupts();
}

void pollSerialControl() {
  while (Serial.available() > 0) {
    const uint8_t b = (uint8_t)Serial.read();

    if (!inFrame) {
      if (b == START_MARKER) { inFrame = true; rxIdx = 0; }
      // any other byte before a start marker is ignored (e.g. nothing)
    } else {
      if (b == END_MARKER) {
        applyFrame(rxBuf, rxIdx);
        lastFrameMs = millis();
        inFrame = false;
      } else if (b == START_MARKER) {
        // unexpected restart -> resync to the new frame
        rxIdx = 0;
      } else {
        if (rxIdx < BUF_LEN) {
          rxBuf[rxIdx++] = b;
        } else {
          inFrame = false;                  // overflow -> drop and resync
        }
      }
    }
  }

#if SERIAL_OVERRIDE_TIMEOUT_MS > 0
  if (serialOverride && (millis() - lastFrameMs > SERIAL_OVERRIDE_TIMEOUT_MS)) {
    noInterrupts();
    serialOverride = false;                 // host goes quiet -> hardware resumes
    interrupts();
  }
#endif
}
