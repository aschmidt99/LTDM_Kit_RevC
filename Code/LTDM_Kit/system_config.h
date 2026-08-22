// system_config.h
#ifndef SYSTEM_CONFIG_H
#define SYSTEM_CONFIG_H

// #define DEBUG // comment out to turn debug mode off
constexpr int SAMPLERATE = 20000; // Sample Rate of TDM
constexpr int ResolutionPWM = 12; // Resolution of PWM timers
constexpr int bufferLength = 2000; // Buffer size (for RMS, zero-crossing frequency meas, etc.)
constexpr float MaxDutyCh1 = 0.35; // Max duty cycle for channel 1 actuation (0.0 to 1.0)
constexpr float MaxDutyCh2 = 1.00; // Max duty cycle for channel 2 actuation (0.0 to 1.0)

#endif