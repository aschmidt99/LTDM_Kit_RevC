#ifndef PINMAP_H
#define PINMAP_H

// OUTPUTS //
// FLEX PWM definitions
constexpr int SENSE_ALT     = 4; // FlexPWM 2.0A - alternate sense pulse (in case of small timing adjustments for S&H)
constexpr int SENSE_PULSE   = 5; // FlexPWM 2.1A - primary sense pulse (triggers ISR, traditionally triggers S&H)
constexpr int CH1_PACTUATE  = 6; // FlexPWM 2.2A (Val2+3) - Channel 1 Actuate PMOS Positive Pulse
constexpr int CH1_NACTUATE  = 9; // FlexPWM 2.2B (Val4+5) - Channel 1 Actuate NMOS Negative Pulse
constexpr int CH2_PACTUATE  = 36; //FlexPWM 2.3A (Val2+3) - Channel 2 Actuate PMOS Positive Pulse
constexpr int CH2_NACTUATE  = 37; //FlexPWM 2.3B (Val4+5) - Channel 2 Actuate NMOS Negative Pulse
constexpr int LED_PULSE     = 33; //FlexPWM 2.0B (Val4+5) - An LED pin that I have yet to figure out exactly what to do with

constexpr int CH1_ENABLE    = 24; // must be high to permit Channel 1 to be on
constexpr int CH2_ENABLE    = 25; // must be high to permit Channel 2 to be on

constexpr int CH1_ADC_PIN       = 14; // (A0) for rectified analog input
constexpr int CH1_POLARITY_PIN  = 34; // for assessing polarity of signal (Postive or Negative)
constexpr int CH1_CURRSENSE_PIN = 27; // (A13) rectified current measurement input.

constexpr int CH2_ADC_PIN       = 15; // (A1?) for rectified analog input
constexpr int CH2_POLARITY_PIN  = 35; // for assessing polarity of signal (Postive or Negative)
constexpr int CH2_CURRSENSE_PIN = 26; // (A12) rectified current measurement input

constexpr int GPIO_PIN = 7; // a random pin for debugging and benchmarking

// INPUTS //
// UI multiplexers for buttons, sliders, and pots
// Buttons
constexpr int DSIN  = 2;
constexpr int DS0   = 32;
constexpr int DS1   = 31;
constexpr int DS2   = 30;
constexpr int DS3   = 3;

// Sliders & Pots
constexpr int ASIN  = 16;
constexpr int AS0   = 38;
constexpr int AS1   = 39;
constexpr int AS2   = 40;
constexpr int AS3   = 41;

// Footpedal inputs
constexpr int FP0  = 22;
constexpr int FP1  = 23;

// TLC5947 LED Driver
constexpr int tlc_data   = 11;
constexpr int tlc_clock  = 13;
constexpr int tlc_latch  = 8;

#endif // PINMAP_H