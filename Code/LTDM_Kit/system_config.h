#ifndef SYSTEM_CONFIG_H
#define SYSTEM_CONFIG_H

// #define DEBUG // comment out to turn debug mode off
constexpr int SAMPLERATE = 20000; // Sample Rate of TDM
constexpr int ResolutionPWM = 12; // Resultion of PWM timers
constexpr int bufferLength = 2000; // Buffer size (for RMS, zero-crossing frequency meas, etc.)

#endif