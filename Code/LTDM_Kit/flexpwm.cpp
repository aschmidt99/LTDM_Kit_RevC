//flexpwm.cpp
#include "flexpwm.h"
#include "pinmap.h"
#include "debug.h"
#include "imxrt.h"
#include "system_config.h"
#include "ui.h"
#include "render.h"
#include "context.h"

// float fbGain = 3.0; // For Lorentz Sensor 4 = very safe
// float adcScale = 1.0; // for attenuating signal when target RMS is achieved

// int currRMS = 0; // the current RMS value of actuated string
// int targetRMS = 2000; // the target RMS value of actuated string (0-4096?)

int noise = 0; // same noise variable for both channels
// float noiseScale = 0;
// int POT2_VAL = 0;

// volatile int CH1_adcValue = 0; // value that channel 1 reads from the string
// volatile int lightThresh = 4096;  //value adc must surpass to trigger light

// volatile bool CH1_polValue = 0;
// volatile bool CH1_lastPolValue = 0;

int deadZone = 0;
volatile int count = 0;
int maxPulseLength = 20000; //nanoseconds

// //for RMS calculation and fundamental frequency estimate
// float freq[N];
// int i = 0;

LorentzContext context = {
  .ch = {
    //Channel 1 (ch[0]) variables
    {
      .fbGain      = 1.0f,
      .adcScale    = 1.0f,
      .noiseScale  = 0.0f,
      .targetRMS   = 2000,
      .adcPin      = CH1_ADC_PIN,
      .polarityPin = CH1_POLARITY_PIN,
      .enablePin   = CH1_ENABLE,
      .in    = 0.0f,
      .out   = 0.0f,
      .polarity  = false,
      .measuredRMS = 0,
      // .outPolValue  = false,
      .lastPolValue = false,
      // .pulseWidth   = 1.0f,
      .activeDamp = false,
      .sampleIndex = 0,
      .sampleSum   = 0
    },

    {
    // Channel 2 (ch[1]) variables
        .fbGain      = 1.0f,
        .adcScale    = 1.0f,
        .noiseScale  = 0.0f,
        .targetRMS   = 2000,
        .adcPin      = CH2_ADC_PIN,
        .polarityPin = CH2_POLARITY_PIN,
        .enablePin   = CH2_ENABLE,
        .in    = 0.0f,
        .out   = 0.0f,
        .polarity  = false,
        .measuredRMS = 0,
        // .outPolValue  = false,
        .lastPolValue = false,
        // .pulseWidth   = 1.0f,
        .activeDamp = false,
        .sampleIndex = 0,
        .sampleSum   = 0
    }
  },
  .buttons = {},
  .sliders = {},
  .pedals = {},
  .sampleRate = SAMPLERATE
};

// void updateRMS(Channel &ch) {
//     // Subtract the oldest sample's square from the running sum
//     ch.sampleSum -= ch.samples[ch.sampleIndex] * ch.samples[ch.sampleIndex];

//     // Store new sample and add its square to running sum
//     ch.samples[ch.sampleIndex] = ch.adcValue;
//     ch.sampleSum += ch.adcValue * ch.adcValue;

//     // Advance circular buffer index
//     ch.sampleIndex = (ch.sampleIndex + 1) % N;

//     // Calculate RMS from running sum
//     ch.measuredRMS = sqrt((float)ch.sampleSum / (float)N);
// }

void flexpwm_sm1_isr() {
  //\\ SENSE STAGE //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//
  // if (status & (1 << 12)) { //VAL0 interrupt (Channel A)
    FLEXPWM2_SM1STS = (1 << 12);  // Writing 1 to bit 12 clears the VAL0 interrupt flag

    // OLD WAY /////////
    // Read inputs
    // CH1.adcValue = analogRead(CH1.adcPin);
    // CH1.inPolValue = digitalRead(CH1.polarityPin);
    // CH2.adcValue = analogRead(CH2.adcPin);
    // CH2.inPolValue = digitalRead(CH2.polarityPin);

    // Populate context
    // NEW WAY - omits the slow and sequential analogRead() - would be interesting to characterize/benchmark this vs old way
    ADC1_HC0 = 7;
    ADC2_HC0 = 8;
    context.ch[0].polarity = digitalRead(context.ch[0].polarityPin);
    context.ch[1].polarity = digitalRead(context.ch[1].polarityPin);
    // CH1.inPolValue = digitalRead(CH1.polarityPin); // old way
    // CH2.inPolValue = digitalRead(CH2.polarityPin);
    while (!(ADC1_HS & ADC_HS_COCO0));  // COCO = "conversion complete"
    while (!(ADC2_HS & ADC_HS_COCO0));
    context.ch[0].in = ADC1_R0 / 4095.0f * float((2*context.ch[0].polarity - 1)); // total input signal, normalized to range of -1.0 to 1.0
    context.ch[1].in = ADC2_R0 / 4095.0f * float((2*context.ch[1].polarity - 1)); // total input signal, normalized to range of -1.0 to 1.0

    // CH1.adcValue = ADC1_R0;
    // CH2.adcValue = ADC2_R0;

  //--------------------------------------------------------------------------------------------------
    //\\// RENDER //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//
    render(&context);

    //\\// PROCESS & APPLY CHANGES /\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/

    // CHANNEL 1 ////////////////
    // CH1.outPolValue = CH1.inPolValue; // at least initially, we apply the same polarity to the output as comes in the input
    // // float pulseWidth = (CH1_adcValue*fbGain/4.0)*(2.0f*float(CH1_polValue) - 1.0f) + dutyHarmonic; // comment back in when ready for harmonic synthesis :)
    // CH1.pulseWidth = CH1.adcScale*(CH1.adcValue*CH1.fbGain/4.0)*(2.0f*float(CH1.inPolValue) - 1.0f) + noise*CH1.noiseScale; // + dutyHarmonic;
    // if (CH1.activeDamp){CH1.pulseWidth = CH1.adcValue*CH1.fbGain*CH1.inPolValue;} // active damp???    

    // // if summmed wave magnitued is negative, actuate other NFET.
    // if (CH1.pulseWidth < 0.0f) { 
    //   CH1.outPolValue = 0;
    // } else {
    //   CH1.outPolValue = 1;
    //  }
    
    // CH1.pulseWidth = fabs(CH1.pulseWidth); // rectify pulse value (for when added noise or synthesized harmonic flips polarity of output

    // // max pulse length check - will need to be smaller than this later.
    // if (CH1.pulseWidth > FLEXPWM2_SM2VAL1*0.6) CH1.pulseWidth= FLEXPWM2_SM2VAL1*0.6;  // I'm worried this is a bit stupid, but for now the sense pulse cannot exceed the total period of one window

    // // CHANNEL 2 /////////////////
    // CH2.outPolValue = CH2.inPolValue; // we apply the same polarity to the output as comes in the input (for basic infinite sustain)
    // // float pulseWidth = (CH1_adcValue*fbGain/4.0)*(2.0f*float(CH1_polValue) - 1.0f) + dutyHarmonic; // comment back in when ready for harmonic synthesis :)
    // CH2.pulseWidth = CH2.adcScale*(CH2.adcValue*CH2.fbGain/4.0)*(2.0f*float(CH2.inPolValue) - 1.0f) + noise*CH2.noiseScale; // + dutyHarmonic;
    //     if (CH2.activeDamp){CH2.pulseWidth = CH2.adcValue*CH2.fbGain*CH2.inPolValue;} // active damp???
        
    // // if summmed wave magnitued is negative, actuate other NFET.
    // if (CH2.pulseWidth < 0.0f) { 
    //   CH2.outPolValue = 0;
    // } else {
    //   CH2.outPolValue = 1;
    //  }
    
    // CH2.pulseWidth = fabs(CH2.pulseWidth); // rectify pulse value

    // // max pulse length check - will need to be smaller than this later.
    // if (CH2.pulseWidth > FLEXPWM2_SM2VAL1*0.5) CH2.pulseWidth = FLEXPWM2_SM2VAL1*0.5;  // I'm worried this is a bit stupid, but for now the sense pulse cannot exceed the total period of one window

  //\\ UPDATE FLEXPWM MODULES  //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//
  // first, we constrain the values to -1.0 to 1.0 in render() returns any out-of-bounds values
    context.ch[0].out = constrain(context.ch[0].out, -1.0f, 1.0f);
    context.ch[1].out = constrain(context.ch[1].out, -1.0f, 1.0f);

    // Using "FLEXPWM2_SM2VAL1/2.0" is deciding that 50% duty cycle is the MAX duty cycle of an actuate pulse
    if (context.ch[0].out > 0) {
      FLEXPWM2_SM2VAL3 = FLEXPWM2_SM2VAL4 + fabs(context.ch[0].out)*(FLEXPWM2_SM2VAL1/2.0);
      FLEXPWM2_SM2VAL5 = FLEXPWM2_SM2VAL4;
    } else if (context.ch[0].out < 0) {
      FLEXPWM2_SM2VAL3 = FLEXPWM2_SM2VAL4;
      FLEXPWM2_SM2VAL5 = FLEXPWM2_SM2VAL4 + fabs(context.ch[0].out)*(FLEXPWM2_SM2VAL1/2.0);
    }

    // APPLY CHANGES
    FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_LDOK(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);
 
    // --------------------------------------------------------------------------------------------------
    //\\ DO REMAINING NON-CRITICAL TASKS //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//
    readUI();

    // Copy values from last time into context
    for (int i = 0; i < 16; i++) {
      context.sliders[i] = sliderStates[i];
      context.buttons[i] = buttonStates[i];
    }
    context.pedals[0] = pedalStates[0];
    context.pedals[1] = pedalStates[1];


  // // THE FOLLOWING NEEDS TO MIGRATE TO RENDER.CPP /OR/ BE RE-MANAGED TO BE A PART OF EACH CHANNEL
    
  //   // GAIN SET BY FIRST KNOB COLUMN 
  //   // CH1.fbGain = sliderStates[0]*4.0;
  //   // CH2.fbGain = sliderStates[4]*4.0;

  //   // TARGET RMS SET BY 2ND KNOB COLUMN
  //   CH1.targetRMS = sliderStates[1]*4096;
  //   // CH1.targetRMS = pedalStates[0]*4096; // USE PEDAL INSTEAD
  //   CH2.targetRMS = sliderStates[5]*4096;

  //   // ADC SCALE WHEN MEASURED RMS TOO BIG
  //   CH1.adcScale = constrain(((float)CH1.targetRMS - (float)CH1.measuredRMS)/1024.0, 0.0, 3.0);
  //   CH2.adcScale = constrain(((float)CH2.targetRMS - (float)CH2.measuredRMS)/1024.0, 0.0, 3.0);

  //   // CH2.adcScale = constrain(1.0 - (CH2.measuredRMS-CH2.targetRMS)/1024.0, 0.0, 1.0);

  //   // MAX NOISE SENT BY 4TH KNOB COLUMN
  //   noise = random(-4096, 4096); // Same noise signal can be used for both
  //   CH1.noiseScale = sliderStates[3]*(constrain(1.0 - (CH1.measuredRMS/1024.0), 0.0, 1.0))*(float)CH1.targetRMS/4096.0f; // divide by 4096 instead of 2048 to leave more noise in the system. Noise currently cuts out entirely when RMS is half of ADC range
  //   CH2.noiseScale = sliderStates[7]*(constrain(1.0 - (CH2.measuredRMS/1024.0), 0.0, 1.0))*(float)CH2.targetRMS/4096.0f; // divide by 4096 instead of 2048 to leave more noise in the system. Noise currently cuts out entirely when RMS is half of ADC range

  //   CH1.activeDamp = buttonStates[8];
  //   CH2.activeDamp = buttonStates[9];

  //   ///CALCULATE RMS
  //   updateRMS(CH1);
  //   updateRMS(CH2);

    // harmonic synthesis omitted for time being
    //
    // // for zero crossing detection
    // if (CH1_polValue != CH1_lastPolValue && CH1_polValue) { //rising edge only
    //   uint32_t currentTime = micros();
    //   uint32_t period = currentTime - lastZeroCrossTime;
    //   lastZeroCrossTime = currentTime;
    //   if (period > 0){
    //     fundamentalFreq = 1e6 / float(period); // Frequency in Hz assuming micros()
    //   }
    //   DEBUG_PRINT(harmN);
    //   DEBUG_PRINT(' ');
    //   // DEBUG_PRINT(500);
    //   // DEBUG_PRINT(' ');
    //   // DEBUG_PRINT(0);
    //   // DEBUG_PRINT(' ');
    //   DEBUG_PRINT(fundamentalFreq);
    //   DEBUG_PRINT(' ');
    //   DEBUG_PRINTLN(avgFrequency);
    //   // if (fundamentalFreq < 500) {
    //     updateAvgFrequency(fundamentalFreq);
    //   // } // remove outliers
    // }
    // CH1_lastPolValue = CH1_polValue;
    //
    // // THINGS THAT CAN BE SLOW OR BEHIND BY 1 SAMPLE: ////
    // fbGain = (analogRead(POT_PIN3)/1204.0); //Read analog pin to determine feedback gain
    // harmGain3rd = (analogRead(POT_PIN2)/4.0); //Read analog pin to determine 3rd harmonic gain
    // harmGain5th = (analogRead(POT_PIN4)/4.0); // Read analog pin to determine 4th harmonic gain
    // // harmGain7th = (analogRead(POT_PIN1)/4.0); // Read analog pin to determine 4th harmonic gain

    // harmN = (analogRead(POT_PIN2)/455+2);
    // harmGainNth = (analogRead(POT_PIN4)/2.0);

    // harmPhase3rd = analogRead(POT_PIN1) / 4095.0; //Read analog pin to adjust harmonic phase
    // harmPhase3rd = 0; //Read analog pin to adjust harmonic phase
    // harmPhase5th = harmPhase3rd; // for now, same phase offset for both
    // harmPhase7th = harmPhase3rd; // for now, same phase offset for both
    // harmPhaseNth = harmPhase3rd; // for now, same phase offset for both


    // phaseIncBase = avgFrequency / float(SAMPLERATE);      // base freq increment at 20kHz PWM
    
    // // Arbitrary Nth harmonic handlings
    // phaseIncNth = phaseIncBase * float(harmN);              // Nth
    // phaseNth += phaseIncNth;
    // if (phaseNth >= 1.0f) phaseNth -= 1.0f;

    // //apply phase offset
    // float adjustedPhaseNth = phaseNth + harmPhaseNth;
    // if (adjustedPhaseNth >= 1.0f) adjustedPhaseNth -= 1.0f;


    // //////// 3RD HARMONIC
    // phaseInc3rd = phaseIncBase * 3.0f;              // 3rd harmonic increment
    // phase3rd += phaseInc3rd;
    // if (phase3rd >= 1.0f) phase3rd -= 1.0f;

    // float adjustedPhase3rd = phase3rd + harmPhase3rd;    //apply phase offset
    // if (adjustedPhase3rd >= 1.0f) adjustedPhase3rd -= 1.0f;

    // //////// 5TH HARMONIC
    // phaseInc5th = phaseIncBase * 5.0f;              // 5th harmonic increment
    // phase5th += phaseInc5th;
    // if (phase5th >= 1.0f) phase5th -= 1.0f;

    // float adjustedPhase5th = phase5th + harmPhase5th;
    // if (adjustedPhase5th >= 1.0f) adjustedPhase5th -= 1.0f;

    // //////// 7TH HARMONIC
    // phaseInc7th = phaseIncBase * 1.0f;              // 7th harmonic increment
    // phase7th += phaseInc7th;
    // if (phase7th >= 1.0f) phase7th -= 1.0f;

    // float adjustedPhase7th = phase7th + harmPhase7th;    // apply phase offset
    // if (adjustedPhase7th >= 1.0f) adjustedPhase7th -= 1.0f;

    // // create 3rd harmonic waveform (square)
    // // float harmonicVal = (adjustedPhase < 0.5f) ? 1.0f : -1.0f;
    // // create 3rd harmonic waveform (sine)
    // float harmonicValNth = getSineFromTable(adjustedPhaseNth);
    // // float harmonicVal3rd = getSineFromTable(adjustedPhase3rd);
    // // float harmonicVal5th = getSineFromTable(adjustedPhase5th);
    // // float harmonicVal7th = getSineFromTable(adjustedPhase7th);
    // // dutyHarmonic = harmonicVal3rd * harmGain3rd + harmonicVal5th * harmGain5th + harmonicVal7th * harmGain7th + harmonicValNth * harmGainNth;
    // dutyHarmonic = harmonicValNth * harmGainNth;
}

void setOutputPWM(uint16_t val) {
  uint32_t PeriodDurCycles = FLEXPWM2_SM2VAL1; // Defines the period length
  uint32_t Cycles = ((uint32_t)val * (PeriodDurCycles + 1)) >> ResolutionPWM;
  if(Cycles > PeriodDurCycles) Cycles = PeriodDurCycles;

  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_CLDOK(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);

  // FOR REFERENCE:
  // #define SENSE_ALT     4 // FlexPWM 2.0A - alternate sense pulse (in case of small timing adjustments for S&H)
  // #define SENSE_PULSE   5 // FlexPWM 2.1A - primary sense pulse (triggers ISR, traditionally triggers S&H)
  // #define CH1_PACTUATE  6 // FlexPWM 2.2A (Val2+3) - Channel 1 Actuate PMOS Positive Pulse
  // #define CH1_NACTUATE  9 // FlexPWM 2.2B (Val4+5) - Channel 1 Actuate NMOS Negative Pulse
  // #define CH2_PACTUATE  36 //FlexPWM 2.3A (Val2+3) - Channel 2 Actuate PMOS Positive Pulse
  // #define CH2_NACTUATE  37 //FlexPWM 2.3B (Val4+5) - Channel 2 Actuate NMOS Negative Pulse
  // #define LED_PULSE     33 //FlexPWM 2.0B (Val4+5) - An LED pin that I have yet to figure out exactly what to do with

  // FOR REFERENCE:
  // VAL0 = 0 for edge-aligned
  // VAL1 = PERIOD of PWM
  // VAL2 = rising edge of A
  // VAL3 = falling edge of A
  // VAL4 = rising edge of B
  // VAL5 = falling edge of B

  // EDGE-ALIGN ALL SUBMODULES
  FLEXPWM2_SM0VAL0 = 0;
  FLEXPWM2_SM1VAL0 = 0;
  FLEXPWM2_SM2VAL0 = 0;
  FLEXPWM2_SM3VAL0 = 0;

  // SENSE pins
  // FLEXPWM2_SM1VAL2 = 0? // SENSE adjust RISING edge (DO NOT ADJUST :)
  FLEXPWM2_SM1VAL3 = Cycles*1.5; // SENSE adjust falling edge
  FLEXPWM2_SM0VAL3 = Cycles*1.5; // SENSE ALT adjusting falling edge

  //CH1 ACTUATE
  // P
  FLEXPWM2_SM2VAL2 = FLEXPWM2_SM1VAL3 + Cycles;         // RISING EDGE
  FLEXPWM2_SM2VAL3 = FLEXPWM2_SM1VAL3 + (Cycles) * 4.0; // FALLING EDGE
  // N
  FLEXPWM2_SM2VAL4 = FLEXPWM2_SM1VAL3 + Cycles;         // RISING EDGE
  FLEXPWM2_SM2VAL5 = FLEXPWM2_SM1VAL3 + (Cycles) * 4.0; // FALLING EDGE

  // CH2 ACTUATE
  // P
  FLEXPWM2_SM3VAL2 = FLEXPWM2_SM1VAL3 + Cycles;         // RISING EDGE
  FLEXPWM2_SM3VAL3 = FLEXPWM2_SM1VAL3 + (Cycles) * 4.0; // FALLING EDGE
  // N
  FLEXPWM2_SM3VAL4 = FLEXPWM2_SM1VAL3 + Cycles;         // RISING EDGE
  FLEXPWM2_SM3VAL5 = FLEXPWM2_SM1VAL3 + (Cycles) * 4.0; // FALLING EDGE

  // LED ACTUATE, just cuz
  FLEXPWM2_SM0VAL4 = FLEXPWM2_SM1VAL3 + Cycles;         // RISING EDGE
  FLEXPWM2_SM0VAL5 = FLEXPWM2_SM1VAL3 + (Cycles) * 4.0; // FALLING EDGE

  // ENABLE OUTPUTS 
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMA_EN(SM0_MASK); // Channel 2.0A - pin 4 Enable
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMB_EN(SM0_MASK); // Channel 2.0B - pin 33 Enable
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMA_EN(SM1_MASK); // Channel 2.1A - pin 5 Enable
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMA_EN(SM2_MASK); // Channel 2.2A - pin 6 Enable
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMB_EN(SM2_MASK); // Channel 2.2B - pin 9 Enable
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMA_EN(SM3_MASK); // Channel 2.3A - pin 36 Enable
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMB_EN(SM3_MASK); // Channel 2.3B - pin 37 Enable
  
  // PUSH CHANGES
  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_LDOK(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);

  *(portConfigRegister(SENSE_ALT)) = 1; //Mask?
  *(portConfigRegister(SENSE_PULSE)) = 1; //Mask?
  *(portConfigRegister(CH1_PACTUATE)) = 1; //Mask?
  *(portConfigRegister(CH1_NACTUATE)) = 1; //Mask?
  *(portConfigRegister(CH2_PACTUATE)) = 1; //Mask?
  *(portConfigRegister(CH2_NACTUATE)) = 1; //Mask?
  *(portConfigRegister(LED_PULSE)) = 1; //Mask?

  IOMUXC_SW_MUX_CTL_PAD_GPIO_B0_06 = 2; // FLEXPWM2_PWM0_A
  IOMUXC_SW_MUX_CTL_PAD_GPIO_B0_07 = 2; // FLEXPWM2_PWM0_B
  IOMUXC_SW_MUX_CTL_PAD_GPIO_B0_08 = 2; // FLEXPWM2_PWM1_A
  IOMUXC_SW_MUX_CTL_PAD_GPIO_B0_09 = 2; // FLEXPWM2_PWM1_B
  IOMUXC_SW_MUX_CTL_PAD_GPIO_B0_10 = 2; // FLEXPWM2_PWM2_A
  IOMUXC_SW_MUX_CTL_PAD_GPIO_B0_11 = 2; // FLEXPWM2_PWM2_B

  IOMUXC_SW_MUX_CTL_PAD_GPIO_B1_02 = 6; // FLEXPWM2_PWM3_A (pin 36)
  IOMUXC_SW_MUX_CTL_PAD_GPIO_B1_03 = 6; // FLEXPWM2_PWM3_B (pin 37)
}

void setOutputFrequency(float frequency) {
  uint32_t CurrentCycles = (uint32_t)((float)F_BUS_ACTUAL / frequency + 0.5);
  uint32_t Prescaler = 0;


  // If frequency too low, switch prescalar
  while (CurrentCycles > 65535 && Prescaler < 7) {
    CurrentCycles = CurrentCycles >> 1;
    Prescaler = Prescaler + 1;
  }
  if (CurrentCycles > 65535){
    CurrentCycles = 65535;
  } else if (CurrentCycles < 2) {
    CurrentCycles = 2; //minimum Cycles --> 10nS or so
  }

  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_CLDOK(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);

  // SM0 (Pin ??)
  FLEXPWM2_SM0CTRL = FLEXPWM_SMCTRL_FULL | FLEXPWM_SMCTRL_PRSC(Prescaler);
  FLEXPWM2_SM0VAL1 = CurrentCycles - 1;

  // SM1 (Pin ??)
  FLEXPWM2_SM1CTRL = FLEXPWM_SMCTRL_FULL | FLEXPWM_SMCTRL_PRSC(Prescaler);
  FLEXPWM2_SM1VAL1 = CurrentCycles - 1;
  
  // SM2 (Pin ??)
  FLEXPWM2_SM2CTRL = FLEXPWM_SMCTRL_FULL | FLEXPWM_SMCTRL_PRSC(Prescaler); //Only update and set prescaler after a full cycle
  FLEXPWM2_SM2VAL1 = CurrentCycles - 1; // set cycles for period duration

  // SM3 (Pin ??)
  FLEXPWM2_SM3CTRL = FLEXPWM_SMCTRL_FULL | FLEXPWM_SMCTRL_PRSC(Prescaler);
  FLEXPWM2_SM3VAL1 = CurrentCycles - 1;
  
  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_LDOK(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);
}

void setInterrupts(){
  FLEXPWM2_SM1STS = 0; // Clear all status flags
  // For Pin 2 SENSE pin
  FLEXPWM2_SM1INTEN |= (1 << 12); // Enable interrupt on VAL0 match (rising edge)
  // For Pin 3 Actuate pin
  // FLEXPWM2_SM2INTEN |= (1 << 14); // Enable interrupt on VAL3 match (rising edge for channel B)

  // FLEXPWM2_SM2INTEN |= (1 << 16); // Enable interrupt on VAL5 match (rising edge for channel B)

  attachInterruptVector(IRQ_FLEXPWM2_1, flexpwm_sm1_isr);
  NVIC_ENABLE_IRQ(IRQ_FLEXPWM2_1);
}

void initADC() {
   // Disable hardware averaging
    ADC1_GC &= ~ADC_GC_AVGE;
    ADC2_GC &= ~ADC_GC_AVGE;

    // Set 12-bit mode while preserving existing clock configuration
    uint32_t cfg1 = ADC1_CFG;
    cfg1 &= ~(ADC_CFG_MODE(3) | ADC_CFG_ADSTS(3) | ADC_CFG_ADLSMP); // clear mode bits only
    cfg1 |= ADC_CFG_MODE(2) | ADC_CFG_ADSTS(3) | ADC_CFG_ADLSMP;    // set 12-bit mode
    ADC1_CFG = cfg1;

    // Set 12-bit mode while preserving existing clock configuration
    uint32_t cfg2 = ADC2_CFG;
    cfg2 &= ~(ADC_CFG_MODE(3) | ADC_CFG_ADSTS(3) | ADC_CFG_ADLSMP); // clear mode bits only
    cfg2 |= ADC_CFG_MODE(2) | ADC_CFG_ADSTS(3) | ADC_CFG_ADLSMP;    // set 12-bit mode
    ADC2_CFG = cfg2;

    // Warm-up trigger
    ADC1_HC0 = 7;
    ADC2_HC0 = 8;
}

void initFlexPWM(){

  pinMode(CH1_ADC_PIN, INPUT);
  pinMode(CH1_POLARITY_PIN, INPUT);
  pinMode(CH1_ENABLE, OUTPUT);

  pinMode(CH2_ADC_PIN, INPUT);
  pinMode(CH2_POLARITY_PIN, INPUT);
  pinMode(CH2_ENABLE, OUTPUT);

  initADC();

  setOutputFrequency(SAMPLERATE);
  setOutputPWM(340);
}