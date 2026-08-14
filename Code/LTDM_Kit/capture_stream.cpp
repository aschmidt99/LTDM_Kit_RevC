#include "capture_stream.h"
#include "ui.h"
#include "pinmap.h"
#include "system_config.h"
#include <Arduino.h>

static const uint32_t SAMPLE_RATE_HZ = SAMPLERATE;
static const uint32_t DEFAULT_CAPTURE_SECONDS = 5;
static const uint32_t MAX_CAPTURE_SECONDS = 30;
static const uint32_t CAPTURE_FIFO_WORDS = 8192; // 8K int16 words, ~16KB buffer
static const uint32_t CAPTURE_FIFO_BYTES = CAPTURE_FIFO_WORDS * sizeof(int16_t);

static volatile bool captureActive = false;
static volatile bool captureRequested = false;
static volatile bool captureFinished = false;
static volatile bool captureArmed = false;
static volatile uint32_t samplesRemaining = 0;
static volatile uint32_t fifoHead = 0;
static volatile uint32_t fifoTail = 0;
static volatile uint32_t fifoCount = 0;
static int16_t captureBuffer[CAPTURE_FIFO_WORDS];

static uint8_t armedCaptureSeconds = DEFAULT_CAPTURE_SECONDS;

static const char CMD_ARM = 'A';
static const char CMD_STOP = 'T';
static const char ARM_ACK[] = "ARMED";
static const uint8_t CAPTURE_MARKER_BYTES[] = {0xAA, 0x55};

static void startCapture(uint32_t seconds) {
  if (captureActive) {
    return;
  }
  if (seconds == 0 || seconds > MAX_CAPTURE_SECONDS) {
    seconds = DEFAULT_CAPTURE_SECONDS;
  }
  samplesRemaining = seconds * SAMPLE_RATE_HZ;
  fifoHead = 0;
  fifoTail = 0;
  fifoCount = 0;
  captureActive = true;
  captureRequested = true;
  captureFinished = false;
  captureArmed = false;
  Serial.write(CAPTURE_MARKER_BYTES, sizeof(CAPTURE_MARKER_BYTES));
}

void captureStreamSetup() {
  fifoHead = 0;
  fifoTail = 0;
  fifoCount = 0;
  captureActive = false;
  captureFinished = false;
  captureArmed = false;
  samplesRemaining = 0;
}

void captureStreamLoop() {
  if (Serial.available() > 0) {
    int nextByte = Serial.peek();
    if (nextByte < 0) {
      return;
    }

    char c = (char)nextByte;
    if (c == CMD_ARM) {
      if (Serial.available() >= 2) {
        Serial.read();
        uint8_t requestedSeconds = (uint8_t)Serial.read();
        if (requestedSeconds == 0 || requestedSeconds > MAX_CAPTURE_SECONDS) {
          requestedSeconds = DEFAULT_CAPTURE_SECONDS;
        }
        armedCaptureSeconds = requestedSeconds;
        captureArmed = true;
        Serial.println(ARM_ACK);
      }
    } else if (c == CMD_STOP) {
      Serial.read();
      captureActive = false;
      captureArmed = false;
      captureFinished = true;
    }
  }

  if (fifoCount > 0) {
    uint32_t maxWrite = Serial.availableForWrite();
    if (maxWrite > 0) {
      uint32_t chunkWords = fifoCount;
      uint32_t chunkBytes = chunkWords * sizeof(int16_t);
      if (chunkBytes > maxWrite) {
        chunkWords = maxWrite / sizeof(int16_t);
        chunkBytes = chunkWords * sizeof(int16_t);
      }
      chunkWords &= ~1u;  // keep word count even so channel pairs remain aligned
      chunkBytes = chunkWords * sizeof(int16_t);
      uint32_t tailToEnd = CAPTURE_FIFO_WORDS - fifoTail;
      if (chunkWords > tailToEnd) {
        chunkWords = tailToEnd & ~1u;
        chunkBytes = chunkWords * sizeof(int16_t);
      }
      if (chunkWords > 0) {
        Serial.write((const uint8_t *)&captureBuffer[fifoTail], chunkBytes);
        fifoTail += chunkWords;
        if (fifoTail >= CAPTURE_FIFO_WORDS) {
          fifoTail = 0;
        }
        fifoCount -= chunkWords;
      }
    }
  }
}

void captureStreamISR(float ch0, float ch1) {
  if (!captureActive) {
    return;
  }

  if (samplesRemaining == 0) {
    captureActive = false;
    captureFinished = true;
    return;
  }

  if (fifoCount + 2 > CAPTURE_FIFO_WORDS) {
    captureActive = false;
    captureFinished = true;
    Serial.println("CAPTURE ERR: FIFO overflow");
    return;
  }

  int16_t s0 = (int16_t)constrain(ch0 * 32767.0f, -32767.0f, 32767.0f);
  int16_t s1 = (int16_t)constrain(ch1 * 32767.0f, -32767.0f, 32767.0f);

  captureBuffer[fifoHead++] = s0;
  if (fifoHead >= CAPTURE_FIFO_WORDS) {
    fifoHead = 0;
  }
  captureBuffer[fifoHead++] = s1;
  if (fifoHead >= CAPTURE_FIFO_WORDS) {
    fifoHead = 0;
  }

  fifoCount += 2;
  samplesRemaining -= 1;

  if (samplesRemaining == 0) {
    captureActive = false;
    captureFinished = true;
  }
}

void captureStreamRequestStart() {
  if (!captureArmed || captureActive) {
    return;
  }

  startCapture(armedCaptureSeconds);
}

bool captureStreamIsActive() {
  return captureActive;
}

bool captureStreamIsArmed() {
  return captureArmed;
}
