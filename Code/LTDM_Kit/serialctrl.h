// serialctrl.h
//
// Optional serial override of the hardware UI.
//
// A host (e.g. the LTDM_Kit_Control Max/MSP patch) can take over the knobs,
// buttons and pedals over USB serial.
//     payload[0] == 0  -> hardware UI (ignore the rest of the frame)
//     payload[0] != 0  -> serial UI (apply the rest of the frame)
//
// While serial override is active, readUI() stops writing the hardware mux into
// the shared state arrays, so render(), the LEDs all follow the serial values.
// 
// Frame layout (all data bytes are 0-127 so they can never collide with the
// 254/255 markers):
//
//   [255]                      start marker
//   [0]    mode                 0 = hardware, !=0 = serial override
//   [1..16]  sliders 0..15      0..250  -> 0.0..1.0
//   [17..32] buttons 0..15      0 or 1
//   [33]   pedal 0              0..250  -> 0.0..1.0
//   [34]   pedal 1              0..250  -> 0.0..1.0
//   [254]                      end marker
//
// = 35 payload bytes between the markers.

#ifndef SERIALCTRL_H
#define SERIALCTRL_H

#include <Arduino.h>

// True while the UI state arrays are being driven by serial instead of hardware.
extern volatile bool serialOverride;

// Safety: if > 0, revert to the hardware UI when no valid frame has arrived for
// this many milliseconds (guards against a crashed/disconnected host leaving the
// unit stuck under serial control). 0 = disabled.
#ifndef SERIAL_OVERRIDE_TIMEOUT_MS
#define SERIAL_OVERRIDE_TIMEOUT_MS 0
#endif

// Non-blocking. Call once per loop() iteration.
void pollSerialControl();

#endif // SERIALCTRL_H
