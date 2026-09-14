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
constexpr float MaxDutyCh2 = 1.00; // Max duty cycle for channel 2 actuation (0.0 to 1.0)

#endif