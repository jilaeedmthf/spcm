# StarHub DDS Driver Handoff For ARTIQ

Date: June 10, 2026

This note is the entry point for implementing the SPCM StarHub DDS driver in
the ARTIQ repository. It summarizes the hardware conclusions from the `spcm`
bring-up repository so the next development session can start from known-good
patterns instead of rediscovering them.

## Repository Reference

Reference repository:

```text
C:\Users\cornelllab\Documents\spcm
```

Branch:

```text
m2p-dds-bringup-tests
```

Useful commits:

```text
71462c0 Add StarHub DDS synchronization tests and notes
824dbe7 Validate gated XIO StarHub triggering
b700978 Add StarHub external reference clock test
f3d20ec Add StarHub DDS phase repeatability test
59bccd5 Add a simple two-tone test for lock-in ref
```

## Hardware

Validated hardware:

```text
/dev/spcm0: M2p.6533-x4, serial 25348
/dev/spcm1: M2p.6533-x4, serial 25350
StarHub sync group: sync0
StarHub carrier/master card: /dev/spcm1
StarHub enable mask for both cards: 0x3
```

For StarHub synchronized operation, the external reference must be connected to
the StarHub carrier/master card:

```text
10 MHz sine reference -> /dev/spcm1 Clk In
```

For a standalone single-card `/dev/spcm0` DDS test, the reference goes directly
to `/dev/spcm0 Clk In`.

## External Clock Configuration

Known-good StarHub clock settings:

```text
configure only /dev/spcm1 for SPC_CM_EXTREFCLOCK
SPC_REFERENCECLOCK = 10_000_000 Hz before setting sample rate
clock input termination = 50 ohm
clock threshold = 0 mV
sample rate = max sample rate
clock output = disabled
require SPC_PLL_ISLOCKED == 1
```

The working source was a 10 MHz sine reference set to 1 Vpp into 50 ohm.
High-impedance clock input did not reliably lock with this source. The card
readback showed:

```text
external-reference range: 128 kHz to 125 MHz
clock threshold range: -5000 mV to +5000 mV
clock threshold step: 1 mV
PLL locked: 1
```

## Channel Range And DDS Amplitude

For M2p.6533, `channels[i].amp(...)` writes `SPC_AMPi`, the analog output
front-end amplitude/range in mV. The M2p.65xx manual states that M2p.653x
supports:

```text
1 mV through 3000 mV into 50 ohm
```

The output stage has 50 ohm series termination. With a high-impedance load, the
physical voltage at the connector is approximately twice the programmed 50 ohm
level. For example:

```text
channel range 3000 mV into 50 ohm -> about 6000 mV into high impedance
```

`dds[core].amp(...)` is separate from `channels[i].amp(...)`: it sets the DDS
carrier amplitude as a fraction of the selected channel range, with unit
conversion handled by the Python wrapper.

## Validated Trigger Behavior

### StarHub Physical Trigger OR

Both physical EXT0 inputs can remain enabled during one uninterrupted StarHub
run. Either card can contribute an accepted local EXT0 trigger to the StarHub
group:

```text
spcm0 EXT0 OR spcm1 EXT0 -> StarHub distributed card trigger -> both DDS engines
```

A card with `SPC_TMASK_NONE` contributes no local trigger source, but still
receives the distributed StarHub trigger if it is included in the StarHub enable
mask.

### XIO Gated Trigger Source

Validated on `/dev/spcm0` without PulseGen firmware:

```text
function generator -> spcm0 X1 positive edge
spcm0 asynchronous X0 -> physical loopback -> spcm0 X2 HIGH gate
X1 edge AND X2 HIGH -> spcm0 trigger engine -> StarHub
    -> spcm0 DDS and spcm1 DDS
```

This supports the intended RFSO timing pattern where the continuous 9.93 Hz
source can be gated before it contributes events to StarHub.

### Repeated StarHub Software Force Trigger

`stack.force_trigger()` is not a one-shot start mechanism. It can be used
repeatedly during one synchronized StarHub run as the distributed CARD trigger
input for DDS commands queued with `SPCM_DDS_TRG_SRC_CARD`.

Validated sequence:

```text
initial exec_now state: DDS output muted, trigger source CARD
queued state 1: CARD trigger -> 300 kHz, 500 mV, 0 deg, trigger source TIMER
queued state 2: TIMER event -> 300 kHz, 500 mV, second phase, trigger source CARD
queued state 3: later CARD trigger -> 300 kHz, 500 mV, third phase

stack.start(M2CMD_CARD_ENABLETRIGGER)
stack.force_trigger()     -> applies state 1 and starts each DDS timer
DDS timer delay elapses   -> applies state 2 on each card
stack.force_trigger()     -> applies pre-queued state 3 on both cards
```

The lock-in showed stable and repeatable cross-card phase. After the later
`stack.force_trigger()`, `/dev/spcm1` reached the configured 120 degree
third-state phase relative to `/dev/spcm0`.

## Driver Design Implications

Use `CardStack` for synchronized operation:

```python
with spcm.CardStack(
    card_identifiers=["/dev/spcm0", "/dev/spcm1"],
    sync_identifier="sync0",
    find_sync=True,
) as stack:
    ...
```

The driver should:

1. Verify `stack.sync_id` points to `/dev/spcm1`.
2. Configure the external 10 MHz reference only on the carrier card.
3. Require PLL lock before starting synchronized DDS output.
4. Configure all cards in DDS mode before `stack.sync_enable(True)`.
5. Start synchronized output through the stack, not individual cards.
6. Use `stack.force_trigger()` as a valid repeated distributed CARD trigger
   during one active run.
7. Use `SPCM_DDS_TRG_SRC_TIMER` for card-local timer advancement only when the
   next queued state should be consumed by the DDS timer.
8. Return to `SPCM_DDS_TRG_SRC_CARD` in a queued command when later StarHub or
   ARTIQ trigger events should advance the sequence.

For RFSO, the important architecture conclusion is:

```text
9.93 Hz gated XIO timing events and ARTIQ timing events can both become StarHub
CARD trigger events, but StarHub does not preserve trigger-source identity.
```

Therefore the ARTIQ driver and timing protocol must guarantee event order if
both sources are enabled, or externally gate/suppress a source when it must not
advance DDS queues.

## Diagnostics And Pass Criteria

Reliable diagnostics:

```text
SPC_PLL_ISLOCKED == 1 on /dev/spcm1
trigger counters advance equally across synchronized cards
DDS status has no QUEUE_OVERRUN
DDS readbacks match requested frequency/amplitude/phase
lock-in phase readout confirms analog behavior
```

Important caveat:

```text
DDS.queue_cmd_count() is useful diagnostic context, but it is not a reliable
pass/fail criterion for finite force-trigger/timer/force-trigger patterns.
```

In the validated repeated-force-trigger test, queue-count deltas could report
zero additional consumption even though the trigger counter advanced, DDS phase
readback changed, DDS status was clean, and the lock-in measured the expected
phase.

`DDS.trg_count()` also did not track every external-triggered DDS update on the
M2p.6533 cards and should not be used as a primary pass criterion.

## Known-Good Script References

Read these first in the `spcm` repo:

```text
src/examples/05_synchronization/6_sync_dds_ext0_or_reference.py
src/examples/05_synchronization/10_sync_dds_xio_trigger_gate.py
src/examples/05_synchronization/11_sync_dds_external_reference_clock.py
src/examples/05_synchronization/12_sync_dds_phase_repeatability_timer.py
src/examples/05_synchronization/README_dds_starhub_tests.md
Notes/StarHub DDS synchronization tests/StarHub DDS synchronization tests.md
Notes/RFSO implementation plan/RFSO implementation plan.md
```

For standalone lock-in reference/two-tone DDS behavior, also read:

```text
src/examples/03_dds/00_dds_two_tone_external_reference.py
```

## Suggested First Prompt For The ARTIQ Repo

Use a prompt like this in the next Codex conversation after the ARTIQ repository
is available:

```text
Work in <absolute path to ARTIQ repository>.

Also use this SPCM bring-up repository as reference:
C:\Users\cornelllab\Documents\spcm

First read:
- Notes/ARTIQ driver handoff/StarHub DDS driver handoff.md
- Notes/RFSO implementation plan/RFSO implementation plan.md
- Notes/StarHub DDS synchronization tests/StarHub DDS synchronization tests.md
- src/examples/05_synchronization/12_sync_dds_phase_repeatability_timer.py
- src/examples/05_synchronization/10_sync_dds_xio_trigger_gate.py

Then inspect the ARTIQ repository's existing Spectrum DDS controller and design
or implement the new RFSO/StarHub DDS driver using the validated hardware
patterns.
```
