//flexpwm.cpp
#include "flexpwm.h"
#include "pinmap.h"
#include "debug.h"
#include "imxrt.h"
#include "system_config.h"
#include "ui.h"
#include "render.h"
#include "context.h"
#include "capture_stream.h"

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

volatile uint16_t g_lastOutputPWMVal = 0;

#if SYNC_MODE == SYNC_MODE_RX
// FORCE_SEL 7 picks EXT_SYNC as the FORCE_OUT source; FRCEN lets that signal
// re-initialise the submodule counter on top of its normal free-running cycle.
constexpr uint16_t SYNC_RX_CTRL2 =
  FLEXPWM_SMCTRL2_FRCEN | FLEXPWM_SMCTRL2_FORCE_SEL(7);

static void routeSyncPinToFlexPWM2() {
  CCM_CCGR2 |= CCM_CCGR2_XBAR1(CCM_CCGR_ON);
  IOMUXC_GPR_GPR6 &= ~IOMUXC_GPR_GPR6_IOMUXC_XBAR_DIR_SEL_16; // INOUT16 is an input
  *(portConfigRegister(SYNC_PIN)) = 1; // GPIO_AD_B0_02 ALT1 = XBAR1_INOUT16
  // Pull-down so an unplugged link idles low instead of floating into EXT_SYNC.
  *(portControlRegister(SYNC_PIN)) =
    IOMUXC_PAD_HYS | IOMUXC_PAD_PKE | IOMUXC_PAD_PUE | IOMUXC_PAD_PUS(0);
  IOMUXC_XBAR1_IN16_SELECT_INPUT = 0; // take XBAR1_IN16 from GPIO_AD_B0_02

  const uint8_t outputs[4] = {
    XBARA1_OUT_FLEXPWM2_PWM0_EXT_SYNC, XBARA1_OUT_FLEXPWM2_PWM1_EXT_SYNC,
    XBARA1_OUT_FLEXPWM2_PWM2_EXT_SYNC, XBARA1_OUT_FLEXPWM2_PWM3_EXT_SYNC
  };
  for (uint8_t out : outputs) {
    volatile uint16_t *sel = &XBARA1_SEL0 + (out / 2);
    if (out & 1) {
      *sel = (*sel & 0x00FF) | ((uint16_t)XBARA1_IN_IOMUX_XBAR_INOUT16 << 8);
    } else {
      *sel = (*sel & 0xFF00) | XBARA1_IN_IOMUX_XBAR_INOUT16;
    }
  }
}

// SM1 VAL4 is otherwise unused (SM1's B output is never enabled), so it serves
// as the compare that opens the window ahead of the master's edge.
constexpr uint16_t SYNC_ARM_FLAG = FLEXPWM_SMSTS_CMPF(1 << 4);

static uint16_t g_syncCtrl2Closed[4]; // CTRL2 image with FRCEN cleared
static bool g_syncGated = false;      // false while acquiring: window stays open

static inline void syncWindowOpen() {
  FLEXPWM2_SM0CTRL2 = g_syncCtrl2Closed[0] | FLEXPWM_SMCTRL2_FRCEN;
  FLEXPWM2_SM1CTRL2 = g_syncCtrl2Closed[1] | FLEXPWM_SMCTRL2_FRCEN;
  FLEXPWM2_SM2CTRL2 = g_syncCtrl2Closed[2] | FLEXPWM_SMCTRL2_FRCEN;
  FLEXPWM2_SM3CTRL2 = g_syncCtrl2Closed[3] | FLEXPWM_SMCTRL2_FRCEN;
}

static inline void syncWindowClose() {
  FLEXPWM2_SM0CTRL2 = g_syncCtrl2Closed[0];
  FLEXPWM2_SM1CTRL2 = g_syncCtrl2Closed[1];
  FLEXPWM2_SM2CTRL2 = g_syncCtrl2Closed[2];
  FLEXPWM2_SM3CTRL2 = g_syncCtrl2Closed[3];
}

static void syncGateSetup() {
  g_syncCtrl2Closed[0] = FLEXPWM2_SM0CTRL2 & ~FLEXPWM_SMCTRL2_FRCEN;
  g_syncCtrl2Closed[1] = FLEXPWM2_SM1CTRL2 & ~FLEXPWM_SMCTRL2_FRCEN;
  g_syncCtrl2Closed[2] = FLEXPWM2_SM2CTRL2 & ~FLEXPWM_SMCTRL2_FRCEN;
  g_syncCtrl2Closed[3] = FLEXPWM2_SM3CTRL2 & ~FLEXPWM_SMCTRL2_FRCEN;
}
#else
constexpr uint16_t SYNC_RX_CTRL2 = 0;
#endif

void flexpwm_sm1_isr() {
#if SYNC_MODE == SYNC_MODE_RX
  const uint16_t sts = FLEXPWM2_SM1STS;
  if (sts & SYNC_ARM_FLAG) {
    FLEXPWM2_SM1STS = SYNC_ARM_FLAG;
    if (g_syncGated) syncWindowOpen();
    if (!(sts & FLEXPWM_SMSTS_RF)) return; // window opened, sense not due yet
  }
  if (g_syncGated) syncWindowClose();
#endif
  //\\ SENSE STAGE //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//
  FLEXPWM2_SM1STS = (1 << 12);  // bit 12 is RF, the reload flag - this ISR fires on reload, not a compare
  uint32_t start = ARM_DWT_CYCCNT;
  delayMicroseconds(3); //small amount of time for S&H Settle
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
  captureStreamISR(context.ch[0].in, context.ch[1].in);
  //\\// RENDER //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//\\//\\//
  render(&context);
  // button 9 drives the motor driver ENN sync line directly from the sense ISR
  digitalWriteFast(MOTOR_ENN_SYNC, context.buttons[9]);
  // button 10 drives the temp fault reset line directly from the sense ISR
  // digitalWriteFast(TEMP_FAULT_RESET, context.buttons[10]);

  //\\ UPDATE FLEXPWM MODULES  //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//
  // first, we constrain the values to -1.0 to 1.0 in render() returns any out-of-bounds values
  context.ch[0].out = constrain(context.ch[0].out, -1.0f, 1.0f);
  context.ch[1].out = constrain(context.ch[1].out, -1.0f, 1.0f);

  // Using "FLEXPWM2_SM2VAL1*0.35f" is deciding that 35% duty cycle is the MAX duty cycle of an actuate pulse
  //CH1
  if (context.ch[0].out > 0) {
    FLEXPWM2_SM2VAL3 = FLEXPWM2_SM2VAL4 + fabs(context.ch[0].out)*(FLEXPWM2_SM2VAL1*MaxDutyCh1);
    FLEXPWM2_SM2VAL5 = FLEXPWM2_SM2VAL4;
  } else if (context.ch[0].out < 0) {
    FLEXPWM2_SM2VAL3 = FLEXPWM2_SM2VAL4;
    FLEXPWM2_SM2VAL5 = FLEXPWM2_SM2VAL4 + fabs(context.ch[0].out)*(FLEXPWM2_SM2VAL1*MaxDutyCh1);
  }

  //CH2 -- LED only, so no longer capable of negative pulse 
  if (context.ch[1].out > 0) {
    FLEXPWM2_SM3VAL3 = FLEXPWM2_SM2VAL4 + fabs(context.ch[1].out)*(FLEXPWM2_SM2VAL1*MaxDutyCh2);
    FLEXPWM2_SM3VAL5 = FLEXPWM2_SM2VAL4;
  } else if (context.ch[1].out <= 0) {
    FLEXPWM2_SM3VAL3 = FLEXPWM2_SM2VAL4;
    FLEXPWM2_SM3VAL5 = FLEXPWM2_SM2VAL4 + fabs(context.ch[1].out)*(FLEXPWM2_SM2VAL1*MaxDutyCh2);
  }

  // APPLY CHANGES
  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_LDOK(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);

  //\\ REMAINING NON-CRITICAL TASKS //\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\//\\/\\//\\//\\//\\//
  readUI(); // updates ui variables in context

  // Copy values from last time into context
  for (int i = 0; i < 16; i++) {
    context.sliders[i] = sliderStates[i];
    context.buttons[i] = buttonStates[i];
  }
  context.pedals[0] = pedalStates[0];
  context.pedals[1] = pedalStates[1];

  context.frameCount++;
  context.isrCycleCount = ARM_DWT_CYCCNT - start;

#if SYNC_MODE == SYNC_MODE_RX
  if (!g_syncGated && context.frameCount > SYNC_RX_ACQUIRE_FRAMES) {
    g_syncGated = true;
  }
#endif
}

void setOutputPWM(uint16_t val) {
  g_lastOutputPWMVal = val;
  uint32_t PeriodDurCycles = FLEXPWM2_SM2VAL1; // Defines the period length
  uint32_t Cycles = ((uint32_t)val * (PeriodDurCycles + 1)) >> ResolutionPWM;
  if(Cycles > PeriodDurCycles) Cycles = PeriodDurCycles;

  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_CLDOK(SM1_MASK | SM2_MASK | SM3_MASK);

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
  FLEXPWM2_SM1VAL0 = 0; // main SENSE pulse
  FLEXPWM2_SM2VAL0 = 0; // CH1 ACTUATE
  FLEXPWM2_SM3VAL0 = 0; // CH2 ACTUATE

  // SENSE pins
  // FLEXPWM2_SM1VAL2 = 0? // SENSE adjust RISING edge (DO NOT ADJUST :)
  FLEXPWM2_SM1VAL3 = Cycles*1.5; // SENSE MAIN - adjust falling edge

  //CH1 ACTUATE
  // PMOS
  FLEXPWM2_SM2VAL2 = FLEXPWM2_SM1VAL3 + Cycles;         // RISING EDGE
  FLEXPWM2_SM2VAL3 = FLEXPWM2_SM1VAL3 + (Cycles) * 4.0; // FALLING EDGE
  // NMOS
  FLEXPWM2_SM2VAL4 = FLEXPWM2_SM1VAL3 + Cycles;         // RISING EDGE
  FLEXPWM2_SM2VAL5 = FLEXPWM2_SM1VAL3 + (Cycles) * 4.0; // FALLING EDGE

  // CH2 ACTUATE
  // PMOS
  FLEXPWM2_SM3VAL2 = FLEXPWM2_SM1VAL3 + Cycles;         // RISING EDGE
  FLEXPWM2_SM3VAL3 = FLEXPWM2_SM1VAL3 + (Cycles) * 4.0; // FALLING EDGE
  // NMOS
  FLEXPWM2_SM3VAL4 = FLEXPWM2_SM1VAL3 + Cycles;         // RISING EDGE
  FLEXPWM2_SM3VAL5 = FLEXPWM2_SM1VAL3 + (Cycles) * 4.0; // FALLING EDGE

  // ENABLE OUTPUTS 
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMA_EN(SM1_MASK); // Channel 2.1A - pin 5 Enable
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMA_EN(SM2_MASK); // Channel 2.2A - pin 6 Enable
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMB_EN(SM2_MASK); // Channel 2.2B - pin 9 Enable
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMA_EN(SM3_MASK); // Channel 2.3A - pin 36 Enable
  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMB_EN(SM3_MASK); // Channel 2.3B - pin 37 Enable
  
  // PUSH CHANGES
  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_LDOK(SM1_MASK | SM2_MASK | SM3_MASK);

  *(portConfigRegister(SENSE_PULSE)) = 1; //Mask?
  *(portConfigRegister(CH1_PACTUATE)) = 1; //Mask?
  *(portConfigRegister(CH1_NACTUATE)) = 1; //Mask?
  *(portConfigRegister(CH2_PACTUATE)) = 1; //Mask?
  *(portConfigRegister(CH2_NACTUATE)) = 1; //Mask?

  IOMUXC_SW_MUX_CTL_PAD_GPIO_B0_08 = 2; // FLEXPWM2_PWM1_A
  IOMUXC_SW_MUX_CTL_PAD_GPIO_B0_09 = 2; // FLEXPWM2_PWM1_B
  IOMUXC_SW_MUX_CTL_PAD_GPIO_B0_10 = 2; // FLEXPWM2_PWM2_A
  // GPIO_B0_11 (pin 33) intentionally left as plain GPIO - see MOTOR_ENN_SYNC

  IOMUXC_SW_MUX_CTL_PAD_GPIO_B1_02 = 6; // FLEXPWM2_PWM3_A (pin 36)
  IOMUXC_SW_MUX_CTL_PAD_GPIO_B1_03 = 6; // FLEXPWM2_PWM3_B (pin 37)

  pinMode(MOTOR_ENN_SYNC, OUTPUT);
  digitalWriteFast(MOTOR_ENN_SYNC, LOW);
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

void setClockedOutputFrequency() {
  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_CLDOK(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);

#if SYNC_MODE == SYNC_MODE_TX
  // Stop the sync generator and FlexPWM2 together. Setting RUN reloads each
  // counter from INIT, so restarting them back-to-back is what phase-locks the
  // sync square to the sense pulse instead of leaving a random offset.
  FLEXPWM1_MCTRL |= FLEXPWM_MCTRL_CLDOK(SM0_MASK);
  FLEXPWM1_MCTRL &= ~FLEXPWM_MCTRL_RUN(SM0_MASK);
  FLEXPWM2_MCTRL &= ~FLEXPWM_MCTRL_RUN(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);
#endif

  // SM0A (pin 4) is the 12.5 MHz clock source. The other submodules use a
  // 6144-tick bus-clock period, exactly 512 times SM0's 12-tick period.
  FLEXPWM2_SM0CTRL = FLEXPWM_SMCTRL_FULL | FLEXPWM_SMCTRL_PRSC(0);
  FLEXPWM2_SM0VAL0 = 0;
  FLEXPWM2_SM0VAL1 = CLOCK_OUTPUT_PERIOD_TICKS - 1;
  FLEXPWM2_SM0VAL2 = 0;
  FLEXPWM2_SM0VAL3 = CLOCK_OUTPUT_PERIOD_TICKS / 2;

    FLEXPWM2_SM1CTRL2 = FLEXPWM_SMCTRL2_INDEP | FLEXPWM_SMCTRL2_WAITEN |
      FLEXPWM_SMCTRL2_CLK_SEL(0) | SYNC_RX_CTRL2;
  FLEXPWM2_SM1CTRL = FLEXPWM_SMCTRL_FULL | FLEXPWM_SMCTRL_PRSC(0);
    FLEXPWM2_SM1VAL1 = SAMPLE_PERIOD_TICKS - 1;

  // SM2 and SM3 retain the sample-rate period used for the actuation pulses.
  FLEXPWM2_SM2CTRL = FLEXPWM_SMCTRL_FULL | FLEXPWM_SMCTRL_PRSC(0);
    FLEXPWM2_SM2VAL1 = SAMPLE_PERIOD_TICKS - 1;
  FLEXPWM2_SM3CTRL = FLEXPWM_SMCTRL_FULL | FLEXPWM_SMCTRL_PRSC(0);
    FLEXPWM2_SM3VAL1 = SAMPLE_PERIOD_TICKS - 1;

#if SYNC_MODE == SYNC_MODE_RX
  // SM0 keeps its 12-tick period so the 12.5 MHz clock stays edge-aligned with
  // the sense window; it just loses at most one tick on each incoming edge.
  FLEXPWM2_SM0CTRL2 |= SYNC_RX_CTRL2;
  FLEXPWM2_SM2CTRL2 |= SYNC_RX_CTRL2;
  FLEXPWM2_SM3CTRL2 |= SYNC_RX_CTRL2;
  FLEXPWM2_SM1VAL4 = SAMPLE_PERIOD_TICKS - SYNC_RX_GATE_TICKS;
  routeSyncPinToFlexPWM2();
  syncGateSetup();
#endif

  FLEXPWM2_OUTEN |= FLEXPWM_OUTEN_PWMA_EN(SM0_MASK);
  FLEXPWM2_OUTEN &= ~FLEXPWM_OUTEN_PWMB_EN(SM0_MASK);
  *(portConfigRegister(SENSE_ALT)) = 1;
  IOMUXC_SW_PAD_CTL_PAD_GPIO_B0_06 =
      IOMUXC_PAD_SRE | IOMUXC_PAD_DSE(7) | IOMUXC_PAD_SPEED(3);
  IOMUXC_SW_MUX_CTL_PAD_GPIO_B0_06 = 2; // FLEXPWM2_PWM0_A, pin 4

  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_LDOK(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);

#if SYNC_MODE == SYNC_MODE_TX
  // FlexPWM1 SM0 is unused by the rest of the firmware, so it carries the
  // inter-kit sync square on its X channel (pin 1) at SAMPLERATE_HZ.
  // PWM_X is low from the counter reload to the VAL0 match, so POLX is needed
  // to put the rising edge - the one EXT_SYNC acts on - at counter 0.
  FLEXPWM1_SM0CTRL2 = FLEXPWM_SMCTRL2_INDEP | FLEXPWM_SMCTRL2_CLK_SEL(0);
  FLEXPWM1_SM0CTRL = FLEXPWM_SMCTRL_FULL | FLEXPWM_SMCTRL_PRSC(0);
  FLEXPWM1_SM0OCTRL = FLEXPWM_SMOCTRL_POLX;
  FLEXPWM1_SM0INIT = 0;
  FLEXPWM1_SM0VAL0 = SAMPLE_PERIOD_TICKS / 2;
  FLEXPWM1_SM0VAL1 = SAMPLE_PERIOD_TICKS - 1;
  FLEXPWM1_OUTEN |= FLEXPWM_OUTEN_PWMX_EN(SM0_MASK);
  *(portConfigRegister(SYNC_PIN)) = 4; // GPIO_AD_B0_02 ALT4 = FLEXPWM1_PWMX00
  FLEXPWM1_MCTRL |= FLEXPWM_MCTRL_LDOK(SM0_MASK);

  FLEXPWM2_MCTRL |= FLEXPWM_MCTRL_RUN(SM0_MASK | SM1_MASK | SM2_MASK | SM3_MASK);
  FLEXPWM1_MCTRL |= FLEXPWM_MCTRL_RUN(SM0_MASK);
#endif
}

void setInterrupts(){
  FLEXPWM2_SM1STS = 0; // Clear all status flags
  // For Pin 2 SENSE pin
  FLEXPWM2_SM1INTEN |= (1 << 12); // Enable interrupt on VAL0 match (rising edge)
#if SYNC_MODE == SYNC_MODE_RX
  FLEXPWM2_SM1INTEN |= FLEXPWM_SMINTEN_CMPIE(1 << 4); // VAL4 compare opens the sync window
#endif
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

  setClockedOutputFrequency();
  setOutputPWM(340);
}