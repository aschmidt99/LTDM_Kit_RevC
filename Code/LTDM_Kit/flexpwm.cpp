//flexpwm.cpp
#include "flexpwm.h"
#include "pinmap.h"
#include "debug.h"
#include "imxrt.h"
#include "system_config.h"
#include "ui.h"
#include "render.h"
#include "context.h"

// int noise = 0; // same noise variable for both channels

LorentzContext context = {
  .ch = {
    //Channel 1 (ch[0]) variables
    {
      .fbGain      = 1.0f,
      .adcScale    = 1.0f,
      .noiseScale  = 0.0f,
      .targetRMS   = 0.0f,

      .adcPin      = CH1_ADC_PIN,
      .polarityPin = CH1_POLARITY_PIN,
      .enablePin   = CH1_ENABLE,
      .in    = 0.0f,
      .out   = 0.0f,
      // .polarity  = false,
      .measuredRMS = 0.0f,
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
        .targetRMS   = 0.1f,

        .adcPin      = CH2_ADC_PIN,
        .polarityPin = CH2_POLARITY_PIN,
        .enablePin   = CH2_ENABLE,
        .in    = 0.0f,
        .out   = 0.0f,
        // .polarity  = false,
        .measuredRMS = 0.0f,
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
  .frameCount = 0
};

void flexpwm_sm1_isr() {
  //\\ SENSE STAGE //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//
  FLEXPWM2_SM1STS = (1 << 12);  // Writing 1 to bit 12 clears the VAL0 interrupt flag
  uint32_t start = ARM_DWT_CYCCNT;
  delayMicroseconds(3); //small amount of time for 
  // Populate context
  // NEW WAY - omits slow/sequential analogRead()
  // Benchmark testing verefied with scope:
  // scenario 1: using analogRead() for each channel makes critical isr time (the time from sense isr leading edge to pushing changes to actuate PWM) take 12.2uS
  // scenario 2: directly addressing ADCs (as done below) cuts this time nearly in half to 6.3uS (now 3.3 after further ADC optimization!)
  // scenario 3: DMA - to be tested!

  ADC1_HC0 = 7;
  ADC2_HC0 = 8;
  // waiting for conversion is the longest part of the process - about 3.3uS
  // some processing /could/ be done in the meantime if desired
  while (!(ADC1_HS & ADC_HS_COCO0) | !(ADC2_HS & ADC_HS_COCO0)); // COCO = "conversion complete"

  // total input signal, normalized to range of -1.0 to 1.0
  context.ch[0].in = ADC1_R0 * 0.0002442f * float((2*digitalRead(context.ch[0].polarityPin) - 1)); // CH1 (0.0002442 is 1/4095 to avoid a divide)
  context.ch[1].in = ADC2_R0 * 0.0002442f * float((2*digitalRead(context.ch[1].polarityPin) - 1)); // CH2 (0.0002442 is 1/4095 to avoid a divide)

  //\\// RENDER //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//
  digitalWriteFast(GPIO_PIN, HIGH);
  render(&context);

  //\\ UPDATE FLEXPWM MODULES  //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//
  // first, we constrain the values to -1.0 to 1.0 in render() returns any out-of-bounds values
  context.ch[0].out = constrain(context.ch[0].out, -1.0f, 1.0f);
  context.ch[1].out = constrain(context.ch[1].out, -1.0f, 1.0f);

  // Using "FLEXPWM2_SM2VAL1*0.35f" is deciding that 35% duty cycle is the MAX duty cycle of an actuate pulse
  //CH1
  if (context.ch[0].out > 0) {
    FLEXPWM2_SM2VAL3 = FLEXPWM2_SM2VAL4 + fabs(context.ch[0].out)*(FLEXPWM2_SM2VAL1*0.35f);
    FLEXPWM2_SM2VAL5 = FLEXPWM2_SM2VAL4;
  } else if (context.ch[0].out < 0) {
    FLEXPWM2_SM2VAL3 = FLEXPWM2_SM2VAL4;
    FLEXPWM2_SM2VAL5 = FLEXPWM2_SM2VAL4 + fabs(context.ch[0].out)*(FLEXPWM2_SM2VAL1*0.35f);
  }

  //CH2
  if (context.ch[1].out > 0) {
    FLEXPWM2_SM3VAL3 = FLEXPWM2_SM2VAL4 + fabs(context.ch[1].out)*(FLEXPWM2_SM2VAL1*0.35f);
    FLEXPWM2_SM3VAL5 = FLEXPWM2_SM2VAL4;
  } else if (context.ch[1].out < 0) {
    FLEXPWM2_SM3VAL3 = FLEXPWM2_SM2VAL4;
    FLEXPWM2_SM3VAL5 = FLEXPWM2_SM2VAL4 + fabs(context.ch[1].out)*(FLEXPWM2_SM2VAL1*0.35f);
  }

  // APPLY CHANGES
  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_LDOK(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);
  digitalWriteFast(GPIO_PIN, LOW);

  // digitalWriteFast(GPIO_PIN, LOW); //  DIAGNOSTICS PIN (Pin 7) LOW

  //\\ REMAINING NON-CRITICAL TASKS //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//
  // digitalWriteFast(GPIO_PIN, HIGH);
  readUI(); // updates ui variables in context
  // digitalWriteFast(GPIO_PIN, LOW);

  // Copy values from last time into context
  for (int i = 0; i < 16; i++) {
    context.sliders[i] = sliderStates[i];
    context.buttons[i] = buttonStates[i];
  }
  context.pedals[0] = pedalStates[0];
  context.pedals[1] = pedalStates[1];

  context.frameCount++;
  context.isrCycleCount = ARM_DWT_CYCCNT - start;
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
  FLEXPWM2_SM0VAL3 = Cycles*3.0; // SENSE ALT adjusting falling edge

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
    // ADC_CFG_MODE(2) = set 12-bit mode; ADC_CFG_MODE(1) = set 10-bit mode
    uint32_t cfg1 = ADC1_CFG;
    cfg1 &= ~(ADC_CFG_MODE(3) | ADC_CFG_ADSTS(3) | ADC_CFG_ADLSMP); // clear mode bits only
    cfg1 |= ADC_CFG_MODE(2) | ADC_CFG_ADSTS(0); // | ADC_CFG_ADLSMP;    // set 12-bit mode
    ADC1_CFG = cfg1;

    uint32_t cfg2 = ADC2_CFG;
    cfg2 &= ~(ADC_CFG_MODE(3) | ADC_CFG_ADSTS(3) | ADC_CFG_ADLSMP); // clear mode bits only
    cfg2 |= ADC_CFG_MODE(2) | ADC_CFG_ADSTS(0); // | ADC_CFG_ADLSMP;    
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