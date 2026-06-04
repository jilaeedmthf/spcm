# DDS StarHub hardware tests

These tests target the two M2p.6533 cards at `/dev/spcm0` and `/dev/spcm1`
connected through `sync0`.

## Retained tests

- `5_sync_dds.py`: basic DDS-mode StarHub start/stop smoke test. Use a scope to
  verify output and relative phase.
- `8_sync_dds_ext0_trigger_or.py`: final interactive test with both physical
  EXT0 inputs enabled simultaneously. This verifies the StarHub trigger OR.
- `9_sync_dds_ext0_trigger_sources.py`: diagnostic test that enables one physical
  EXT0 source at a time and sets the other card's trigger mask to `NONE`.

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
