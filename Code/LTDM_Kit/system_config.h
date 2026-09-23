// system_config.h
#ifndef SYSTEM_CONFIG_H
#define SYSTEM_CONFIG_H

#include <cstdint>

// #define DEBUG // comment out to turn debug mode off
constexpr uint32_t FLEXPWM_BUS_CLOCK_HZ = 150'000'000;
constexpr uint16_t CLOCK_OUTPUT_PERIOD_TICKS = 12;
constexpr uint16_t CLOCKS_PER_SAMPLE = 512;
constexpr uint16_t SAMPLE_PERIOD_TICKS =
	CLOCK_OUTPUT_PERIOD_TICKS * CLOCKS_PER_SAMPLE;
constexpr float CLOCK_OUTPUT_HZ =
	float(FLEXPWM_BUS_CLOCK_HZ) / CLOCK_OUTPUT_PERIOD_TICKS; // 12.5 MHz
constexpr float SAMPLERATE_HZ =
	float(FLEXPWM_BUS_CLOCK_HZ) / SAMPLE_PERIOD_TICKS; // 24,414.0625 Hz

constexpr int ResolutionPWM = 12; // Resolution of PWM timers
constexpr int bufferLength = 2000; // Buffer size (for RMS, zero-crossing frequency meas, etc.)
constexpr float MaxDutyCh1 = 0.35; // Max duty cycle for channel 1 actuation (0.0 to 1.0)
constexpr float MaxDutyCh2 = 0.35; // Max duty cycle for channel 2 actuation (0.0 to 1.0)
// ---- MULTI-KIT SYNCHRONIZATION -------------------------------------------
// Two kits sitting close together electromagnetically couple: one kit's
// actuate pulse lands inside the other kit's sense window and reads as string
// velocity. Tying their sense/actuate windows together removes the collision.
//
// Wire pin 1 ("GPIO1") and GND of the SYNC_TX kit to pin 1 and GND of the
// SYNC_RX kit. Exactly one kit on the link may be SYNC_TX.
//
// The link lives on FlexPWM1, which this firmware otherwise never touches, so
// every FlexPWM2 output (including the 12.5 MHz clock on pin 4) is unaffected.
//
//   SYNC_MODE_OFF - standalone.
//   SYNC_MODE_TX  - master. Pin 1 (FlexPWM1.0_X) emits a 50% duty square at
//                   SAMPLERATE_HZ, rising edge on the sense instant.
//   SYNC_MODE_RX  - slave. Pin 1 feeds XBAR1_INOUT16, which drives EXT_SYNC on
//                   all four FlexPWM2 submodules so every counter restarts on
//                   the master's edge. The receiver keeps the same period as
//                   the master: it still has to reach its own modulo each
//                   cycle or the full-cycle reload never fires and the
//                   actuation values stop transferring out of LDOK.
#define SYNC_MODE_OFF 0
#define SYNC_MODE_TX  1
#define SYNC_MODE_RX  2

// Because both kits' crystals agree to a few ppm, a genuine sync edge can only
// land within a few ticks of where the receiver predicts it. The receiver arms
// EXT_SYNC only inside that window and ignores the rest of the cycle, which
// blanks the actuate period where the EMI lands.
constexpr uint16_t SYNC_RX_GATE_TICKS = 64; // window opens this early, ~427 ns

// The window is held wide open for this long after boot so the link can lock
// before gating starts. Covers the master being powered up second.
constexpr uint32_t SYNC_RX_ACQUIRE_FRAMES = (uint32_t)(5.0f * SAMPLERATE_HZ);

// ---- CHANGE THIS LINE BETWEEN UPLOADS ----
#define SYNC_MODE SYNC_MODE_RX
#endif