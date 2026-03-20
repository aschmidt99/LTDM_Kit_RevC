// creates a sinewave lookup table for fast harmonic synthesis

#include "SineTable.h"
#include <math.h>

float sineTable[SINE_TABLE_SIZE];

void initSineTable() {
  for (int i = 0; i < SINE_TABLE_SIZE; i++) {
    float phase = (float)i / (float)SINE_TABLE_SIZE;
    sineTable[i] = sinf(2.0f * 3.14159265359f * phase);
  }
}

float getSineFromTable(float phase) {
  int index = (int)(phase * SINE_TABLE_SIZE) % SINE_TABLE_SIZE;
  return sineTable[index];
}