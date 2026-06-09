# DDS StarHub hardware tests

These tests target the two M2p.6533 cards at `/dev/spcm0` and `/dev/spcm1`
connected through `sync0`.

## Retained tests

- `5_sync_dds.py`: basic DDS-mode StarHub start/stop smoke test. Use a scope to
  verify output and relative phase.
- `6_sync_dds_ext0_or_reference.py`: concise driver-reference pattern for
  selecting multiple physical EXT0 trigger-source cards.
- `8_sync_dds_ext0_trigger_or.py`: final interactive test with both physical
  EXT0 inputs enabled simultaneously. This verifies the StarHub trigger OR.
- `9_sync_dds_ext0_trigger_sources.py`: diagnostic test that enables one physical
  EXT0 source at a time and sets the other card's trigger mask to `NONE`.
- `10_sync_dds_xio_trigger_gate.py`: tests whether `spcm0` can contribute
  `rising_edge(X1) AND X2_HIGH` to StarHub while X0 controls the X2 gate through
  a physical loopback. This passed on the two-card M2p.6533 stack and does not
  require PulseGen firmware.
- `11_sync_dds_external_reference_clock.py`: tests the StarHub carrier's
  external-reference clock input with a conservative 10 MHz sine configuration.
  It configures `/dev/spcm1` as the external-reference master, keeps the clock
  input high impedance by default unless `--clock-termination-50ohm` is passed,
  and then attempts a small-amplitude DDS StarHub trigger smoke test. The
  1 Vpp, 50-ohm sine reference passed with `--clock-termination-50ohm`.

## Pass criteria

For physical-trigger tests, use these two measurements:

- Both cards' trigger-engine counters advance by the same positive amount.
- Both DDS queue command counts decrease by the same positive amount.

`DDS.trg_count()` is printed only as diagnostic context where present. On these
M2p.6533 cards it did not track each consumed external-trigger DDS update.

## Electrical defaults

The physical EXT0 tests use:

- positive-edge trigger;
- 0.5 V threshold;
- DC coupling;
- high-impedance input by default.

Pass `--termination` only when the trigger source is intended to drive a 50 ohm
load.

The external-reference clock test starts with:

- 10 MHz reference frequency;
- high-impedance clock input;
- 0 mV clock threshold;
- clock output disabled;
- 20 mV DDS output amplitude.

Use `--clock-termination-50ohm` when the reference source is intended to drive a
50 ohm clock input at the desired voltage. The tested 10 MHz source was set to
1 Vpp into 50 ohm and locked successfully with this option.
