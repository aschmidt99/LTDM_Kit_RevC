# LTDM Firmware Telemetry Contract v1

Status: Phase 2 draft contract
Owner: LTDM firmware + Python capture integration
Last updated: 2026-08-22

## Goal
Define a stable telemetry contract from Teensy firmware to Python host so trial metadata can be populated from firmware authority, using meaningful labels rather than raw register names.

## Design Principles
- Preserve current capture behaviour and timing.
- Keep ARM/START workflow backward-compatible.
- Emit telemetry before binary stream starts.
- Use UTF-8 line-delimited JSON frames for easy parsing.
- Keep field names aligned with trial_metadata_schema_v2.md.

## Backward Compatibility
Existing protocol today:
- Host sends `A` + 1-byte duration seconds.
- Firmware responds with `ARMED\n`.
- On start trigger, firmware sends marker bytes `0xAA 0x55`.
- Firmware then streams binary int16 audio payload.

v1 telemetry keeps all of the above unchanged and adds framed telemetry lines after ARMED, before marker.

## Wire Format
Each telemetry frame is one UTF-8 line:
- Prefix: `@TLM1 `
- Payload: one compact JSON object
- Terminator: `\n`

Example line:
`@TLM1 {"message_type":"arm_snapshot","protocol_version":"1",...}\n`

Notes:
- Prefix prevents accidental collisions with debug text.
- JSON payload must be single-line.
- No telemetry frames are sent after marker `0xAA55`.

## Message Sequence
1. Host sends ARM command `A <duration_byte>`.
2. Firmware validates duration and arms capture.
3. Firmware sends `ARMED\n` (legacy ack).
4. Firmware sends one required telemetry frame (`arm_snapshot`).
5. Optionally firmware may send additional `@TLM1` frames for diagnostics.
6. User presses start trigger.
7. Firmware sends marker bytes `0xAA 0x55`.
8. Firmware streams binary capture data.

## Required Telemetry Message
`message_type = "arm_snapshot"`

Required top-level fields:
- message_type: string, fixed `arm_snapshot`
- protocol_version: string, fixed `1`
- firmware:
  - samplerate_hz: number
  - resolution_pwm_bits: number
  - max_duty_ch1: number
  - max_duty_ch2: number
- flexpwm_tdm_timing:
  - reference:
    - time_zero_symbol: string, fixed `FLEXPWM2_SM0VAL0`
    - time_zero_cycle: number
  - config_constants:
    - samplerate_hz: number
    - max_duty_ch1: number
    - max_duty_ch2: number
    - resolution_pwm_bits: number
  - derived:
    - val_input: number
    - period_cycles: number
    - period_us: number
    - cycles: number
    - cycles_formula: string
  - consistency_checks:
    - all_actuation_start_times_equal: boolean
  - timing_table:
    - array of rows:
      - label: string
      - cycle_value: number
      - duty_cycle: number
      - time_us: number
- controls:
  - raw_state:
    - buttons: bool[16]
    - sliders: number[16] in [0,1]
    - pedals: number[2] in [0,1]
  - assignment_map:
    - source: string enum (`firmware_reported` preferred)
    - version_tag: string
    - entries: object containing button_0..button_15, slider_0..slider_15, pedal_0..pedal_1
      - values are meaningful labels or `N/A`
  - interpreted_state:
    - channel_1 and channel_2 objects when available

## Required Timing Labels
`flexpwm_tdm_timing.timing_table` must include at least:
- `main_sense_pulse_end`
- `alt_sense_pulse_start`
- `alt_sense_pulse_end`
- `actuation_pulse_start`

## Conversion Rules
- `period_us = 1e6 / samplerate_hz`
- `duty_cycle = 100 * (cycle_value / period_cycles)`
- `time_us = (cycle_value - time_zero_cycle) * (period_us / period_cycles)`

## Current Firmware Mapping (for implementation)
From flexpwm.cpp:
- `period_cycles` comes from `FLEXPWM2_SM2VAL1 + 1`.
- `val_input` is the input to `setOutputPWM(val)`.
- `cycles` is computed as `((uint32_t)val * period_cycles) >> ResolutionPWM`.
- `main_sense_pulse_end` maps to `FLEXPWM2_SM1VAL3`.
- `alt_sense_pulse_start` maps to `FLEXPWM2_SM0VAL0`.
- `alt_sense_pulse_end` maps to `FLEXPWM2_SM0VAL3`.
- `actuation_pulse_start` maps to `FLEXPWM2_SM2VAL2`.
- Equality check compares `SM2VAL2`, `SM2VAL4`, `SM3VAL2`, and `SM3VAL4`.

## Host Parsing Requirements
- Keep existing `ARMED` and marker handling.
- After ARMED, accumulate and parse `@TLM1 ` lines until marker arrives.
- Ignore malformed telemetry frames, but continue capture.
- If no valid telemetry frame is parsed, set metadata `report_source` fallback appropriately.

## Failure Behaviour
- Telemetry frame parse failure alone does not abort capture.
- Missing required telemetry fields marks firmware telemetry status as failed for metadata.
- Trial may still complete with trial_status failed if required telemetry is missing by schema policy.

## Example Telemetry Frame
@TLM1 {"message_type":"arm_snapshot","protocol_version":"1","firmware":{"samplerate_hz":20000,"resolution_pwm_bits":12,"max_duty_ch1":0.35,"max_duty_ch2":1.0},"flexpwm_tdm_timing":{"reference":{"time_zero_symbol":"FLEXPWM2_SM0VAL0","time_zero_cycle":0},"config_constants":{"samplerate_hz":20000,"max_duty_ch1":0.35,"max_duty_ch2":1.0,"resolution_pwm_bits":12},"derived":{"val_input":340,"period_cycles":7500,"period_us":50.0,"cycles":622,"cycles_formula":"cycles = (val * period_cycles) >> resolution_pwm_bits"},"consistency_checks":{"all_actuation_start_times_equal":true},"timing_table":[{"label":"main_sense_pulse_end","cycle_value":933,"duty_cycle":12.44,"time_us":6.22},{"label":"alt_sense_pulse_start","cycle_value":0,"duty_cycle":0.0,"time_us":0.0},{"label":"alt_sense_pulse_end","cycle_value":1866,"duty_cycle":24.88,"time_us":12.44},{"label":"actuation_pulse_start","cycle_value":1555,"duty_cycle":20.73,"time_us":10.37}]},"controls":{"raw_state":{"buttons":[1,0,0,0,0,0,1,0,0,0,0,0,0,0,0,0],"sliders":[0.42,0.18,0.90,0.31,0.08,0.50,0.49,0.12,0,0,0,0,0,0,0,0],"pedals":[0.0,0.0]},"assignment_map":{"source":"firmware_reported","version_tag":"render_map_v1","entries":{"button_0":"channel_1.enable","button_1":"channel_2.enable","button_2":"channel_1.rms_limiting_enabled","button_6":"channel_1.noise_enable","button_8":"capture_start_trigger","button_9":"N/A"}}}}
