# LTDM Trial Metadata Schema

Status: Phase 1 complete (approved)
Owner: LTDM capture workflow
Last updated: 2026-08-23

## Purpose
This schema defines the canonical trial metadata contract for LTDM data acquisition.
It applies to:
- Teensy stream captures
- Interface captures
- Rigol captures
- Audacity timeline/project automation metadata

The schema is not versioned; it is expected to be the single finalised contract as the
workflow matures. The canonical file is `trials/trial_####/trial_metadata.json` — it is the
only per-trial metadata file (there is no separate `trial_manifest.json` or operational
metadata file). When a trial is built up across multiple script invocations (for example a
Teensy+interface capture followed by a Rigol scope capture for the same trial), each script
loads the existing `trial_metadata.json` and merges in its own `streams`/`files` entries.

Two companion files at the experiment level (in `orchestration/`) hold metadata that is
intentionally *not* duplicated into `trial_metadata.json` verbatim:
- `experiment_profile.json`: fields that are normally stable across the whole experiment
  (`experiment_description`, string/magnet setup, channel labels). Every other user-reported
  field is copied into each trial's `trial_metadata.json` as `experiment_profile_snapshot`
  (`experiment_description` is the only field excluded from that snapshot, since it's
  experiment-scoped, not trial-scoped). `trial_metadata.json` also stores a relative pointer to
  this file (`experiment_profile_path`).
  - If a field's value differs from what was used in the previous trial, capture scripts detect
    this automatically and rewrite that field's value in `experiment_profile.json` to the literal
    string `"VARIABLE"`. This is a marker, not a usable value: once a field is `"VARIABLE"`, every
    subsequent trial is prompted for that field's actual value for that trial (defaulting to the
    previous trial's value), and the prompted value is what's recorded in that trial's
    `experiment_profile_snapshot` — `experiment_profile.json` itself never holds the real value
    again once a field is flagged this way.
  - Right after the trial number is entered (in `run_trial.py`, or in `rigol/capture.py` when run
    standalone), the user is optionally offered a questionary menu to directly change any
    user-reported field for the upcoming trial; edits are saved to `experiment_profile.json`
    immediately, so the change-detection above treats them the same as a hand-edit of the file.
- `trials_diff.json`: auto-rebuilt after every trial by recursively diffing every trial's
  `trial_metadata.json`. Nested values are flattened into columns, and only fields whose value
  actually differs across at least two trials are kept (plus `trial_number`). Generated file
  lists, capture timestamps, monotonic timing, Audacity lifecycle event timestamps, interface
  alignment measurements, and interface channel peak/RMS measurements are omitted. Derived host
  timing measurements are also omitted. Control changes are taken from `controls.interpreted_state`;
  numeric knob, slider, or pedal values are truncated to two decimal places and only count as
  changed when the readings differ by more than `0.01`. Button and mode values are compared exactly.

`trial_description` is prompted for on every trial (by whichever capture script starts that trial
— pre-filled from that same trial's own prior value when overwriting/rerunning a trial) and is
stored directly on `trial_metadata.json`. The operator is prompted once when the experiment profile
is created and stored in `experiment_profile.json`.
next.

## Core Decisions (locked)
- Trial identity is experiment_title + trial_number.
- No global trial_id is required.
- Firmware-reported values are the highest authority.
- Both UTC wall-clock timestamps and monotonic timing diagnostics are stored.
- Numeric values are stored as JSON numbers, not strings.
- Units are encoded in field names (for example, sample_rate_hz, magnet_distance_mm).
- All file paths are stored relative to experiment root.
- Partial captures are marked failed.
- Audacity project lifecycle events are included.
- Backward compatibility with old metadata keys is not required.
- All controls are recorded. If a control has no active assignment, use N/A in assignment_map.

## Value Authority Order
When multiple sources disagree, use this precedence:
1. firmware_reported
2. measured_file_properties
3. python_defaults

## Top-Level Object
Required top-level keys:
- experiment_title
- trial_number
- trial_description
- operator (stored once in experiment_profile.json)
- capture_profile
- trial_status
- capture_time_utc
- capture_time_local
- firmware
- tdm_timing
- controls
- streams
- files
- experiment_profile_path
- experiment_profile_snapshot
- experiment_profile_path

Optional top-level keys:
- duration_seconds
- capture_options
- timing
- audacity
- errors

## Field Specification

### 1) Identity
- experiment_title: string, required
- trial_number: integer >= 1, required
- trial_description: string, required (may be empty string; prompted once per trial)
- operator: string, experiment-scoped (required in experiment_profile.json; prompted once when the profile is created)
- capture_profile: string, required
- trial_status: string enum, required
  - allowed: success, failed
- capture_time_utc: string (ISO 8601 UTC), required
- capture_time_local: string (ISO 8601 with timezone offset), required
- duration_seconds: integer, optional
- capture_options: object, optional (raw capture-script settings, for example port/device names)

### 2) Timing
- timing: object, optional
- timing.monotonic: object, optional
  - t_arm_send_s: number, optional
  - t_armed_ack_s: number, optional
  - t_marker_s: number, optional
  - t_capture_done_s: number, optional
  - t_stop_cmd_s: number, optional
- timing.derived: object, optional
  - arm_ack_ms: number, optional
  - record_cmd_after_marker_ms: number, optional
  - teensy_capture_after_marker_s: number, optional
- timing.wall_clock: object, optional
  - capture_start_utc: string, optional
  - capture_end_utc: string, optional

### 3) Firmware authority block
- firmware: object, required
  - report_raw: object, optional (raw firmware arm_snapshot dump, minus message_type/protocol_version;
    samplerate_hz is available at report_raw.firmware.samplerate_hz and streams.teensy.sample_rate_hz)

### 4) Controls block
- controls: object, required

- controls.raw_state: object, required
  - buttons: array[16] of boolean, required
  - sliders: array[16] of number in [0, 1], required
  - pedals: array[2] of number in [0, 1], optional

- controls.interpreted_state: object, optional
  - channel_1: object, optional
    - gain: number, optional
    - rms_limiting_enabled: boolean, optional
    - target_rms: number, optional
    - noise_level: number, optional
    - enabled: boolean, optional
  - channel_2: object, optional
    - gain: number, optional
    - rms_limiting_enabled: boolean, optional
    - target_rms: number, optional
    - noise_level: number, optional
    - enabled: boolean, optional
  - global_modes: object, optional

- controls.assignment_map: object, required
  - source: string enum, required
    - allowed: inferred_from_render, firmware_reported, manual
  - version_tag: string, required
  - entries: object, required
    - keys: button_0..button_15, slider_0..slider_15, pedal_0..pedal_1
    - values: string assignment label, or N/A

Assignment map policy:
- Uncertain or currently unassigned controls must be represented explicitly with N/A.
- Capture must not fail solely because mapping is uncertain.

### 4b) TDM timing block
- tdm_timing: object, required

- tdm_timing.config_constants: object, required
  - samplerate_hz: number, required
  - max_duty_ch1: number, required
  - max_duty_ch2: number, required
  - resolution_pwm_bits: number, required

- tdm_timing.derived: object, required
  - cycles: number, required
  - val_input: number, required
  - sample_period_us: number, required
  - period_cycles: number, required
  - cycles_formula: string, required

- tdm_timing.consistency_checks: object, required
  - all_actuation_start_times_equal: boolean, required
  - note: string, optional

- tdm_timing.timing_table: array, required
  - each row is an object:
    - label: string, required
    - cycle_value: number, required
    - duty_cycle: number, required
    - time_us: number, required

Timing table policy:
- duty_cycle is normalised by sample period from SAMPLERATE.
- time_us is measured relative to FLEXPWM2_SM0VAL0 (time zero; not stored as a metadata field).
- Include at least these rows:
  - main_sense_pulse_end
  - alt_sense_pulse_start
  - alt_sense_pulse_end
  - actuation_pulse_start

Recommended conversion formulas:
- sample_period_us = 1e6 / samplerate_hz
- duty_cycle = 100 * (cycle_value / period_cycles)
- time_us = (cycle_value - FLEXPWM2_SM0VAL0) * (sample_period_us / period_cycles)

Current firmware context (for implementation reference):
- SAMPLERATE, MaxDutyCh1, MaxDutyCh2 are defined in system_config.h.
- Cycles is derived in setOutputPWM() from ResolutionPWM and period cycles.
- FLEXPWM2_SM2VAL2/4 and FLEXPWM2_SM3VAL2/4 are currently initialised to the same rising-edge cycle.

Internal implementation mapping (not stored as metadata keys):
- main_sense_pulse_end := FLEXPWM2_SM1VAL3
- alt_sense_pulse_start := FLEXPWM2_SM0VAL0
- alt_sense_pulse_end := FLEXPWM2_SM0VAL3
- actuation_pulse_start := FLEXPWM2_SM2VAL2 (equivalent to SM2VAL4, SM3VAL2, SM3VAL4 in current setup)

### 5) Stream execution
- streams: object, required

- streams.teensy: object, required
  - requested: boolean, required
  - status: string enum, required
    - allowed: success, failed, skipped
  - sample_rate_hz: number, required when requested is true
  - channels: integer, required when requested is true

- streams.interface: object, required
  - requested: boolean, required
  - status: string enum, required
    - allowed: success, failed, skipped
  - sample_rate_hz: number, required when requested is true
  - channels: integer, required when requested is true

- streams.rigol: object, required
  - requested: boolean, required
  - status: string enum, required
    - allowed: success, failed, skipped
  - sample_rate_hz: number, optional
  - points_per_channel: integer, optional

Trial failure policy:
- If any requested stream has status failed, trial_status must be failed.

### 6) Files (relative paths only)
- files: object, required

- files.teensy: object, optional
  - raw_bin: string, optional
  - ch1_wav: string, optional
  - ch2_wav: string, optional

- files.interface: object, optional
  - ch1_wav: string, optional
  - ch2_wav: string, optional

- files.rigol: object, optional
  - hdf5: string, optional
  - png: string, optional
  - screen_png: string, optional
  - scope_capture_id: string, optional

### 7) Audacity
- audacity: object, optional
  - enabled: boolean, required when audacity object exists
  - project: object, optional
    - path: string, optional (relative)
    - status: string enum, optional
      - allowed: created, opened, saved, failed
  - timeline_state_path: string, optional (relative)
  - lifecycle_events: array, optional
    - each event is an object:
      - ts_utc: string
      - event: string enum
        - allowed: launch_attempt, launch_success, open_project, create_project, import_tracks, save_project, close_project, error
      - details: object

### 8) Experiment profile snapshot
- experiment_profile_path: string, required (relative path to `orchestration/experiment_profile.json`)
- experiment_profile_snapshot: object, required
  - Contains this trial's actual value for every `experiment_profile.json` field except
    `experiment_title`, `experiment_description`, and `updated_at`.
  - For a field whose `experiment_profile.json` value is the literal string `"VARIABLE"`, the
    snapshot holds the value prompted for on this specific trial.
  - For any other field, the snapshot holds `experiment_profile.json`'s literal value; if that
    literal value differs from what the previous trial recorded, `experiment_profile.json` is
    rewritten to `"VARIABLE"` for that field (from then on it's always prompted per-trial).
- `experiment_description` is experiment-scoped, entered once when the experiment is created, and
  lives only in `orchestration/experiment_profile.json` (never in per-trial files).

### 9) Errors
- errors: array, optional
- each item:
  - code: string, required
  - message: string, required
  - component: string enum, required
    - allowed: teensy, interface, rigol, audacity, orchestration

## Minimal Required Record Example
{
  "experiment_title": "FinalForNow",
  "trial_number": 7,
  "trial_description": "Baseline pluck, magnet at 5cm",
  "operator": "adamschmidt",
  "capture_profile": "teensy_interface_no_audacity",
  "trial_status": "success",
  "capture_time_utc": "2026-08-21T15:30:00Z",
  "capture_time_local": "2026-08-21T16:30:00+01:00",
  "firmware": {
    "samplerate_hz": 20000,
    "protocol_version": "1",
    "report_source": "firmware"
  },
  "tdm_timing": {
    "config_constants": {
      "samplerate_hz": 20000,
      "max_duty_ch1": 0.35,
      "max_duty_ch2": 1.0,
      "resolution_pwm_bits": 12
    },
    "derived": {
      "cycles": 622,
      "val_input": 340,
      "sample_period_us": 50.0,
      "period_cycles": 7500,
      "cycles_formula": "cycles = (val * (period_cycles + 1)) >> resolution_pwm_bits"
    },
    "consistency_checks": {
      "all_actuation_start_times_equal": true
    },
    "timing_table": [
      {"label": "main_sense_pulse_end", "cycle_value": 933, "duty_cycle": 12.44, "time_us": 6.22},
      {"label": "alt_sense_pulse_start", "cycle_value": 0, "duty_cycle": 0.0, "time_us": 0.0},
      {"label": "alt_sense_pulse_end", "cycle_value": 1866, "duty_cycle": 24.88, "time_us": 12.44},
      {"label": "actuation_pulse_start", "cycle_value": 1555, "duty_cycle": 20.73, "time_us": 10.37}
    ]
  },
  "controls": {
    "raw_state": {
      "buttons": [true, false, false, false, false, false, true, false, false, false, false, false, false, false, false, false],
      "sliders": [0.42, 0.18, 0.90, 0.31, 0.08, 0.50, 0.49, 0.12, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00]
    },
    "assignment_map": {
      "source": "inferred_from_render",
      "version_tag": "render_map_v1",
      "entries": {
        "button_0": "channel_1.enable",
        "button_1": "channel_2.enable",
        "button_2": "channel_1.rms_limiting_enabled",
        "button_6": "channel_1.noise_enable",
        "button_8": "capture_start_trigger",
        "button_9": "N/A"
      }
    }
  },
  "streams": {
    "teensy": {"requested": true, "status": "success", "sample_rate_hz": 20000, "channels": 2},
    "interface": {"requested": true, "status": "success", "sample_rate_hz": 192000, "channels": 2},
    "rigol": {"requested": false, "status": "skipped"}
  },
  "files": {
    "teensy": {
      "raw_bin": "trials/trial_0007/macro_audio/teensy_stream.bin",
      "ch1_wav": "trials/trial_0007/macro_audio/teensy_stream_ch1.wav",
      "ch2_wav": "trials/trial_0007/macro_audio/teensy_stream_ch2.wav"
    }
  },
  "experiment_profile_path": "orchestration/experiment_profile.json",
  "experiment_profile_snapshot": {
    "string_material": "steel",
    "magnet_position_cm": "5"
  }
}
