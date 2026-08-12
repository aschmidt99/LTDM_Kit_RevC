// visualAlias.cpp

#include "visualAlias.h"
#include "system_config.h"
#include "SineTable.h"

float ledPhase = 0.0f;

float renderLEDPulse(float freqHz, float freqOffsetHz, float threshold, float phaseOffset) {
  float pulseFreq = freqHz + freqOffsetHz;
  if (pulseFreq < 0.0f) pulseFreq = 0.0f; // no accidental negative freqs!

  float phaseInc = pulseFreq / float(SAMPLERATE);
  ledPhase += phaseInc;
  if (ledPhase >= 1.0f) ledPhase -=1.0f;

  // shift which point in the cycle we compare against, so you can manually
  // slide the "frozen" position when freq offset = 0 lands somewhere boring
  float shiftedPhase = ledPhase + phaseOffset;
  if (shiftedPhase >= 1.0f) shiftedPhase -= 1.0f;

  float sineVal = getSineFromTable(shiftedPhase); // -1.0..1.0
  return (sineVal > threshold) ? 1.0f : 0.0f;
}