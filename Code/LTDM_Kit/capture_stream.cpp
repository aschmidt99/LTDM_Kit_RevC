#include "capture_stream.h"
#include "context.h"
#include "flexpwm.h"
#include "ui.h"
#include "pinmap.h"
#include "system_config.h"
#include <Arduino.h>

static const uint32_t SAMPLE_RATE_HZ = SAMPLERATE;
static const uint32_t DEFAULT_CAPTURE_SECONDS = 5;
static const uint32_t MAX_CAPTURE_SECONDS = 120;
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

static void print_json_bool(bool v) {
  Serial.print(v ? "true" : "false");
}

static const char *button_assignment_label(int idx) {
  switch (idx) {
    case 0: return "channel_1.enable";
    case 1: return "channel_2.enable";
    case 2: return "channel_1.rms_limiting_enabled";
    case 6: return "channel_1.noise_enable";
    case 8: return "capture_start_trigger";
    default: return "N/A";
  }
}

static const char *slider_assignment_label(int idx) {
  switch (idx) {
    case 0: return "channel_1.gain";
    case 1: return "channel_1.target_rms";
    case 2: return "channel_1.noise_lpf";
    case 3: return "channel_1.noise_scale";
    case 4: return "harmonics.alpha";
    case 5: return "visual_alias.led_threshold";
    case 6: return "visual_alias.led_freq_offset";
    case 7: return "visual_alias.led_phase_offset";
    case 8: return "harmonics.gain_1";
    case 9: return "harmonics.gain_2";
    case 10: return "harmonics.gain_3";
    case 11: return "harmonics.gain_4";
    case 12: return "harmonics.gain_5";
    case 13: return "harmonics.gain_6";
    case 14: return "harmonics.gain_7";
    case 15: return "harmonics.gain_8";
    default: return "N/A";
  }
}

static float duty_cycle_percent(uint32_t cycle_value, uint32_t period_cycles) {
  if (period_cycles == 0) {
    return 0.0f;
  }
  return 100.0f * ((float)cycle_value / (float)period_cycles);
}

static float time_us_from_zero(uint32_t cycle_value, uint32_t zero_cycle, float period_us, uint32_t period_cycles) {
  if (period_cycles == 0) {
    return 0.0f;
  }
  return ((float)((int32_t)cycle_value - (int32_t)zero_cycle)) * (period_us / (float)period_cycles);
}

static void emit_arm_snapshot_telemetry(uint8_t requested_seconds) {
  const uint32_t time_zero_cycle = (uint32_t)FLEXPWM2_SM0VAL0;
  const uint32_t period_cycles = (uint32_t)FLEXPWM2_SM2VAL1 + 1u;
  const float period_us = (SAMPLERATE > 0) ? (1000000.0f / (float)SAMPLERATE) : 0.0f;
  const uint32_t cycles = ((uint32_t)g_lastOutputPWMVal * period_cycles) >> ResolutionPWM;

  const uint32_t main_sense_pulse_end = (uint32_t)FLEXPWM2_SM1VAL3;
  const uint32_t alt_sense_pulse_start = (uint32_t)FLEXPWM2_SM0VAL0;
  const uint32_t alt_sense_pulse_end = (uint32_t)FLEXPWM2_SM0VAL3;
  const uint32_t actuation_pulse_start = (uint32_t)FLEXPWM2_SM2VAL2;

  const bool actuation_start_equal =
      ((uint32_t)FLEXPWM2_SM2VAL2 == (uint32_t)FLEXPWM2_SM2VAL4) &&
      ((uint32_t)FLEXPWM2_SM2VAL2 == (uint32_t)FLEXPWM2_SM3VAL2) &&
      ((uint32_t)FLEXPWM2_SM2VAL2 == (uint32_t)FLEXPWM2_SM3VAL4);

  Serial.print("@TLM1 {");
  Serial.print("\"message_type\":\"arm_snapshot\",");
  Serial.print("\"protocol_version\":\"1\",");
  Serial.print("\"duration_requested_s\":");
  Serial.print((uint32_t)requested_seconds);
  Serial.print(",\"firmware\":{");
  Serial.print("\"samplerate_hz\":");
  Serial.print((uint32_t)SAMPLERATE);
  Serial.print(",\"resolution_pwm_bits\":");
  Serial.print((uint32_t)ResolutionPWM);
  Serial.print(",\"max_duty_ch1\":");
  Serial.print(MaxDutyCh1, 6);
  Serial.print(",\"max_duty_ch2\":");
  Serial.print(MaxDutyCh2, 6);
  Serial.print("},\"flexpwm_tdm_timing\":{");
  Serial.print("\"reference\":{\"time_zero_symbol\":\"FLEXPWM2_SM0VAL0\",\"time_zero_cycle\":");
  Serial.print(time_zero_cycle);
  Serial.print("},\"config_constants\":{");
  Serial.print("\"samplerate_hz\":");
  Serial.print((uint32_t)SAMPLERATE);
  Serial.print(",\"max_duty_ch1\":");
  Serial.print(MaxDutyCh1, 6);
  Serial.print(",\"max_duty_ch2\":");
  Serial.print(MaxDutyCh2, 6);
  Serial.print(",\"resolution_pwm_bits\":");
  Serial.print((uint32_t)ResolutionPWM);
  Serial.print("},\"derived\":{");
  Serial.print("\"cycles\":");
  Serial.print(cycles);
  Serial.print(",\"val_input\":");
  Serial.print((uint32_t)g_lastOutputPWMVal);
  Serial.print(",\"period_us\":");
  Serial.print(period_us, 6);
  Serial.print(",\"period_cycles\":");
  Serial.print(period_cycles);
  Serial.print(",\"cycles_formula\":\"cycles = (val * period_cycles) >> resolution_pwm_bits\"},");
  Serial.print("\"consistency_checks\":{\"all_actuation_start_times_equal\":");
  print_json_bool(actuation_start_equal);
  Serial.print("},\"timing_table\":[");

  Serial.print("{\"label\":\"main_sense_pulse_end\",\"cycle_value\":");
  Serial.print(main_sense_pulse_end);
  Serial.print(",\"duty_cycle\":");
  Serial.print(duty_cycle_percent(main_sense_pulse_end, period_cycles), 4);
  Serial.print(",\"time_us\":");
  Serial.print(time_us_from_zero(main_sense_pulse_end, time_zero_cycle, period_us, period_cycles), 4);
  Serial.print("},");

  Serial.print("{\"label\":\"alt_sense_pulse_start\",\"cycle_value\":");
  Serial.print(alt_sense_pulse_start);
  Serial.print(",\"duty_cycle\":");
  Serial.print(duty_cycle_percent(alt_sense_pulse_start, period_cycles), 4);
  Serial.print(",\"time_us\":");
  Serial.print(time_us_from_zero(alt_sense_pulse_start, time_zero_cycle, period_us, period_cycles), 4);
  Serial.print("},");

  Serial.print("{\"label\":\"alt_sense_pulse_end\",\"cycle_value\":");
  Serial.print(alt_sense_pulse_end);
  Serial.print(",\"duty_cycle\":");
  Serial.print(duty_cycle_percent(alt_sense_pulse_end, period_cycles), 4);
  Serial.print(",\"time_us\":");
  Serial.print(time_us_from_zero(alt_sense_pulse_end, time_zero_cycle, period_us, period_cycles), 4);
  Serial.print("},");

  Serial.print("{\"label\":\"actuation_pulse_start\",\"cycle_value\":");
  Serial.print(actuation_pulse_start);
  Serial.print(",\"duty_cycle\":");
  Serial.print(duty_cycle_percent(actuation_pulse_start, period_cycles), 4);
  Serial.print(",\"time_us\":");
  Serial.print(time_us_from_zero(actuation_pulse_start, time_zero_cycle, period_us, period_cycles), 4);
  Serial.print("}]},\"controls\":{");

  Serial.print("\"raw_state\":{\"buttons\":[");
  for (int i = 0; i < 16; i++) {
    if (i) Serial.print(",");
    print_json_bool(buttonStates[i]);
  }
  Serial.print("],\"sliders\":[");
  for (int i = 0; i < 16; i++) {
    if (i) Serial.print(",");
    Serial.print(sliderStates[i], 6);
  }
  Serial.print("],\"pedals\":[");
  Serial.print(pedalStates[0], 6);
  Serial.print(",");
  Serial.print(pedalStates[1], 6);
  Serial.print("]},");

  Serial.print("\"assignment_map\":{\"source\":\"firmware_reported\",\"version_tag\":\"render_map_v1\",\"entries\":{");
  for (int i = 0; i < 16; i++) {
    if (i) Serial.print(",");
    Serial.print("\"button_");
    Serial.print(i);
    Serial.print("\":\"");
    Serial.print(button_assignment_label(i));
    Serial.print("\"");
  }
  for (int i = 0; i < 16; i++) {
    Serial.print(",\"slider_");
    Serial.print(i);
    Serial.print("\":\"");
    Serial.print(slider_assignment_label(i));
    Serial.print("\"");
  }
  for (int i = 0; i < 2; i++) {
    Serial.print(",\"pedal_");
    Serial.print(i);
    Serial.print("\":\"N/A\"");
  }
  Serial.print("}},");

  Serial.print("\"interpreted_state\":{");
  Serial.print("\"channel_1\":{");
  Serial.print("\"gain\":");
  Serial.print(context.ch[0].fbGain, 6);
  Serial.print(",\"rms_limiting_enabled\":");
  print_json_bool(buttonStates[2]);
  Serial.print(",\"target_rms\":");
  Serial.print(context.ch[0].targetRMS, 6);
  Serial.print(",\"noise_level\":");
  Serial.print(context.ch[0].noiseScale, 6);
  Serial.print(",\"enabled\":");
  print_json_bool(buttonStates[0]);
  Serial.print("},\"channel_2\":{");
  Serial.print("\"gain\":");
  Serial.print(context.ch[1].fbGain, 6);
  Serial.print(",\"target_rms\":");
  Serial.print(context.ch[1].targetRMS, 6);
  Serial.print(",\"enabled\":");
  print_json_bool(buttonStates[1]);
  Serial.print("},\"global_modes\":{");
  Serial.print("\"capture_armed\":");
  print_json_bool(captureArmed);
  Serial.print("}}}}");
  Serial.println();
}

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
        emit_arm_snapshot_telemetry(requestedSeconds);
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
