// creates a sinewave lookup table for fast harmonic synthesis

#ifndef SINETABLE_H
#define SINETABLE_H

#define SINE_TABLE_SIZE 256

extern float sineTable[SINE_TABLE_SIZE];

void initSineTable();
float getSineFromTable(float phase);

#endif