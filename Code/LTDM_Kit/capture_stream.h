#ifndef CAPTURE_STREAM_H
#define CAPTURE_STREAM_H

#include <Arduino.h>

void captureStreamSetup();
void captureStreamLoop();
void captureStreamISR(float ch0, float ch1);
void captureStreamRequestStart();
bool captureStreamIsActive();
bool captureStreamIsArmed();

#endif // CAPTURE_STREAM_H
