# StarHub DDS synchronization hardware tests

Date: June 4, 2026

## Goal

Validate the synchronization and multi-card trigger behavior needed by the RFSO
implementation plan using the two M2p.6533 cards connected through StarHub.

Hardware:

- `/dev/spcm0`: M2p.6533-x4, serial 25348
- `/dev/spcm1`: M2p.6533-x4, serial 25350
- StarHub sync group: `sync0`
- StarHub carrier card: `/dev/spcm1`
- StarHub enable mask for both cards: `0x3`

## RFSO hardware-test checklist status

| RFSO implementation-plan item | Status | Result |
| --- | --- | --- |
| Test communication to each card | Partial pass | Both cards open, configure, and report DDS/trigger state independently. `exec_now` communication latency has not been quantified. |
| Test StarHub synchronization | Pass | Both cards run in DDS mode through `sync0`; StarHub reports two synchronized cards. |
| Test trigger modes from multiple cards | Pass for physical EXT0 | Either card's physical Trig In can trigger both synchronized DDS engines. |
| Test multiple trigger sources without restart | Pass | Both EXT0 inputs can remain enabled simultaneously and are combined by StarHub OR during one uninterrupted run. |
| Test actual XIO trigger source | Pass | `spcm0` contributes `rising_edge(X1) AND X2_HIGH` to StarHub. Asynchronous X0 controls looped-back X2 while the synchronized DDS stack remains running. |
| Test actual ARTIQ trigger source | Pending | StarHub routing is validated, but the final ARTIQ TTL source still needs testing. |
| Test external 10 MHz clock input | Pass | `/dev/spcm1` locked to a 10 MHz sine reference when the source was set to 1 Vpp into 50 ohm and the card clock input was 50-ohm terminated. |
| Test multitone lock-in reference | Pending | Not covered by these tests. |
| Test measurement loop without ARTIQ | Pending | Not covered by these tests. |

## Validated trigger behavior

### Single physical trigger source

Each card was tested as the only enabled EXT0 source while the other card used
trigger mask `NONE`.

Validated paths:

```text
spcm0 EXT0 -> StarHub -> spcm0 DDS and spcm1 DDS
spcm1 EXT0 -> StarHub -> spcm0 DDS and spcm1 DDS
```

For both source cards:

- the null test with no external trigger remained idle;
- both DDS queues remained in `WAITING_FOR_TRG`;
- an external EXT0 edge incremented both trigger-engine counters equally;
- both DDS queues consumed the same number of commands.

### Physical trigger-source OR

Both cards were configured with `SPC_TMASK_EXT0` during one uninterrupted
StarHub run. The trigger cable was moved between the two Trig In ports without
stopping or reconfiguring the cards.

Results:

| Physical source | Trigger counter change | DDS queue change | Result |
| --- | --- | --- | --- |
| `spcm0` EXT0 | Both cards: `0 -> 2` | Both cards: `31 -> 29` | Pass |
| `spcm1` EXT0 | Both cards: `2 -> 13` | Both cards: `29 -> 18` | Pass |

The number of applied pulses was greater than one in both tests. The important
result is that the two cards advanced by identical amounts.

Conclusion:

```text
spcm0 EXT0 OR spcm1 EXT0 -> StarHub -> both synchronized DDS engines
```

works without stopping, reconfiguring, or restarting the stack.

### What creates the StarHub OR

`SPC_TMASK_EXT0` does not create the cross-card OR by itself. It tells one card's
local trigger engine to contribute its physical EXT0 input as a trigger source.

The cross-card OR is created by the combination of:

1. configuring `SPC_TMASK_EXT0` on more than one card;
2. enabling those cards together through the StarHub sync mask;
3. starting/arming the cards through the StarHub stack.

A card configured with `SPC_TMASK_NONE` contributes no local trigger source, but
it remains a synchronized trigger receiver. If it is included in the StarHub
enable mask, it still receives triggers contributed by the source cards.

For a future four-card stack with two physical Trig In sources:

| Card | Local trigger mask | Role |
| --- | --- | --- |
| `spcm0` | `SPC_TMASK_EXT0` | Contributes Trig In source A |
| `spcm1` | `SPC_TMASK_NONE` | Receives synchronized trigger only |
| `spcm2` | `SPC_TMASK_EXT0` | Contributes Trig In source B |
| `spcm3` | `SPC_TMASK_NONE` | Receives synchronized trigger only |

The resulting trigger path is:

```text
spcm0 EXT0 OR spcm2 EXT0
    -> StarHub distributed card trigger
    -> DDS engines on spcm0, spcm1, spcm2, and spcm3
```

Every DDS engine must use `SPCM_DDS_TRG_SRC_CARD` to consume the distributed
card-trigger event. The concise driver-reference implementation is:

`src/examples/05_synchronization/6_sync_dds_ext0_or_reference.py`

## Important DDS diagnostics

For these M2p.6533 cards, `DDS.trg_count()` did not increment for every external
triggered DDS update and must not be used as the primary pass criterion.

Reliable evidence of triggered DDS execution was:

1. Both cards' `SPC_TRIGGERCOUNTER` values advanced by the same positive amount.
2. Both cards' DDS queue command counts decreased by the same positive amount.
3. With no trigger, both queues remained unchanged with DDS status
   `WAITING_FOR_TRG`.

The physical trigger tests use an immediate DDS initialization command:

```text
set DDS trigger source and initial tone -> exec_now
queue later phase updates -> exec_at_trg
```

This matches the intended controller behavior: establish a known running state,
then consume synchronized updates on later trigger events.

## RFSO architecture implications

The StarHub OR result supports connecting two always-enabled timing sources:

- one source for the phase-reference/T0 path, eventually produced by XIO;
- one source for ARTIQ-timed sequence actions.

No trigger-mask switch is required between these sources. Trigger masks are card
configuration and cannot be changed while the cards are running.

However, StarHub OR does not preserve trigger-source identity. A trigger from
either enabled EXT0 source becomes the same synchronized card-trigger event.
Therefore, either source advances the next waiting DDS command on every
synchronized card.

The RFSO controller must account for this. It cannot queue one command expecting
only the XIO trigger and another command expecting only the ARTIQ trigger unless
the external timing protocol guarantees the event order. Possible strategies:

- define one shared, deterministic trigger-event schedule;
- gate one physical trigger source externally when it must not advance DDS;
- move one class of updates to a different DDS mechanism, such as timer or
  immediate commands;
- use separate hardware functionality when source-specific routing is required.

## Validated XIO trigger-engine gate

### Motivation

The rest of the experiment requires an uninterrupted 9.93 Hz signal, but the
9.93 Hz events must sometimes be prevented from advancing the StarHub DDS
queues. The ARTIQ trigger must remain available during those intervals.

The current two cards do not have the PulseGen firmware option. The first test
should therefore use a laboratory pulse generator as the continuous 9.93 Hz
source. If the trigger-gating behavior is validated, PulseGen can later be
licensed on one card to produce two synchronized continuous 9.93 Hz outputs:

```text
future Card A XIO output 0 -> uninterrupted 9.93 Hz for the rest of the system
future Card A XIO output 1 -> Card B XIO trigger input
```

Card B does not need PulseGen. Its main trigger engine acts as the logic
gate. One XIO trigger input receives the 9.93 Hz source, and another receives a
HIGH/LOW gate-enable level. The intended local trigger expression is:

```text
Card B local trigger = rising_edge(9.93 Hz XIO input) AND gate-enable XIO HIGH
```

Accepted Card B trigger events are contributed directly to StarHub. Card B does
not need to generate a physical gated-copy output:

```text
Card B accepted 9.93 Hz events OR ARTIQ trigger from another source card
    -> StarHub distributed card trigger
    -> all synchronized DDS engines
```

The AND mask is local to Card B. It should suppress Card B's 9.93 Hz
contribution without suppressing the ARTIQ trigger contributed by another
StarHub card.

### Card B XIO assignment

| Card B XIO | Role |
| --- | --- |
| XIO output | Gate-enable level controlled as an asynchronous output |
| XIO input 1 | Receives the gate-enable level through a short loopback cable |
| XIO input 2 | Receives the continuous 9.93 Hz signal |
| Remaining XIO | Reserved; optional diagnostic output if useful |

Validated trigger-engine configuration:

```text
OR mask:  9.93 Hz XIO input, positive-edge mode
AND mask: gate-enable XIO input, HIGH-level mode
```

A Card B asynchronous XIO output drives the gate-enable input through a short
physical loopback.

### Capability-probe result

On June 5, 2026, `spcm0` accepted and read back the gate configuration
without a PulseGen license:

| Required capability | Result |
| --- | --- |
| X0 asynchronous output | Pass |
| X1 trigger input | Pass |
| X2 trigger input | Pass |
| X1/EXT1 available in trigger OR mask | Pass |
| X2/EXT2 available in trigger AND mask | Pass |
| X1/EXT1 positive-edge mode available in OR mask | Pass |
| X2/EXT2 HIGH-level mode available in AND mask | Pass |

Relevant readbacks:

```text
available trigger OR mask:  0x1f
available trigger AND mask: 0x1f
X0 mode:                    0x2  (ASYNCOUT)
X1 mode:                    0x10 (TRIGIN)
X2 mode:                    0x10 (TRIGIN)
trigger OR mask:            0x4  (EXT1)
trigger AND mask:           0x8  (EXT2)
X1/EXT1 trigger mode:       0x1  (positive edge)
X2/EXT2 trigger mode:       0x8  (HIGH level)
```

This confirms that the required XIO routing and trigger-engine Boolean
configuration exist on the installed M2p.6533 hardware.

A stopped-card electrical loopback probe requested X0 LOW, HIGH, then LOW.
Looped-back X2 followed all three states correctly. X0 itself remained LOW in
the asynchronous register readback even while physical X2 was HIGH, so the X0
bit must not be used to validate its output state on this hardware.

During an initial synchronized runtime test, asynchronous X0 successfully
changed looped-back X2 through LOW, HIGH, then LOW while both cards remained
running. Neither card triggered because the function-generator signal was not
yet reaching X1. A separate two-second X1 input probe showed:

```text
saw X1 LOW:              no
saw X1 HIGH:             yes
sampled X1 rising edges:  0
sampled X1 falling edges: 0
```

After correcting the function-generator connection, the X1 input probe observed
20 rising and 20 falling edges in two seconds from the 10 Hz, 3.3 V, 20% duty
cycle signal.

The full StarHub test then passed:

| Gate state | Trigger-counter change | DDS queue change | Result |
| --- | --- | --- | --- |
| Initial X0/X2 LOW, 1.5 s | Both cards: `+0` | Both cards: `0` consumed | Pass |
| X0/X2 HIGH, measured 1.5 s window | Both cards: `+15` | Both cards: `15` consumed | Pass |
| Final X0/X2 LOW, 1.5 s | Both cards: `+0` | Both cards: `0` consumed | Pass |

Two additional synchronized triggers occurred during the 150 ms settling period
immediately after opening the gate, giving a total trigger counter of 17 before
the gate was closed. This is expected for a continuously running 10 Hz source
and shows that the gate transition takes effect immediately rather than at the
start of the later measurement window.

Validated path:

```text
function generator -> spcm0 X1 positive edge
spcm0 asynchronous X0 -> physical loopback -> spcm0 X2 HIGH gate
X1 edge AND X2 HIGH -> spcm0 trigger engine -> StarHub
    -> spcm0 DDS and spcm1 DDS
```

This confirms that the M2p.6533 trigger engine can perform the required gate
without a PulseGen license and without stopping or reconfiguring the StarHub
stack.

### Remaining hardware tests

1. Verify an ARTIQ or laboratory trigger contributed by another StarHub card
   still consumes every DDS queue while Card B's 9.93 Hz gate is LOW.
2. Characterize asynchronous X0 host-command latency and determine whether it is
   acceptable for the RFSO timing protocol.
3. Boundary and endurance test:
   - measure behavior when the gate changes near a 9.93 Hz rising edge;
   - verify no extra, shortened, or duplicated trigger event is produced;
   - run long enough to verify stable trigger counts and synchronized DDS queue
     consumption.

### Pass criteria

- Gate-enable LOW blocks every Card B 9.93 Hz contribution.
- Gate-enable HIGH passes exactly one Card B trigger per 9.93 Hz rising edge.
- ARTIQ triggers from the other source card remain active in both gate states.
- Every accepted event advances all synchronized DDS queues equally.
- The gate state can be changed without stopping or reconfiguring the cards.
- No boundary transition creates an unintended StarHub trigger.

The configuration, runtime asynchronous X0-to-X2 switching, local Boolean gate,
and gated StarHub distribution are validated on the M2p.6533 hardware.

## External 10 MHz reference clock test

On June 8, 2026, `src/examples/05_synchronization/11_sync_dds_external_reference_clock.py`
tested the 10 MHz sine reference on the two-card StarHub stack.

Required wiring for the StarHub stack:

```text
10 MHz sine reference -> /dev/spcm1 StarHub carrier/master clock input
```

The reference must be connected to the clock/reference input, not to EXT0 or
the XIO trigger inputs. The working configuration used a 10 MHz sine source set
to 1 Vpp into 50 ohm and enabled 50-ohm clock-input termination on `/dev/spcm1`.
The script sets the clock threshold to 0 mV, writes the 10 MHz reference
frequency before the sample rate, disables clock output, and uses only 20 mV DDS
output amplitude for the smoke test.

Live card readbacks from `/dev/spcm1`:

```text
external-reference range: 128 kHz to 125 MHz
clock threshold range:    -5000 mV to +5000 mV
clock threshold step:     1 mV
clock mode:               0x20 (SPC_CM_EXTREFCLOCK)
reference clock:          10000000 Hz
clock termination:        50 ohm
clock threshold:          0 mV
PLL locked:               1
```

The StarHub stack reported both cards and both DDS queues consumed the same
number of synchronized commands:

```text
StarHub carrier index: /dev/spcm1
StarHub enable mask:   0x3
DDS commands consumed: [7, 7]
```

Conclusion: the M2p.6533 StarHub stack can lock to the external 10 MHz sine
reference when the source and card are both configured for 50 ohm. An earlier
high-impedance attempt with the same 0 mV threshold did not report PLL lock, so
future tests should use 50-ohm termination for this 1 Vpp, 50-ohm reference.

## Test scripts

- `src/examples/05_synchronization/5_sync_dds.py`
  - DDS-mode StarHub smoke test.
- `src/examples/05_synchronization/6_sync_dds_ext0_or_reference.py`
  - Concise multi-card/multi-source trigger configuration reference.
- `src/examples/05_synchronization/8_sync_dds_ext0_trigger_or.py`
  - Final simultaneous physical EXT0 OR test.
- `src/examples/05_synchronization/9_sync_dds_ext0_trigger_sources.py`
  - One-source-at-a-time physical EXT0 diagnostic.
- `src/examples/05_synchronization/10_sync_dds_xio_trigger_gate.py`
  - XIO trigger-engine AND-gate capability probe and StarHub behavior test.
- `src/examples/05_synchronization/11_sync_dds_external_reference_clock.py`
  - StarHub carrier external-reference clock test using conservative
    low-voltage 10 MHz sine settings.
- `src/examples/03_dds/09_dds_external_trigger.py`
  - Single-card physical EXT0 reference test.

## Next hardware tests

1. Characterize asynchronous X0 gate-control latency while the StarHub DDS group
   is running.
2. Connect the intended ARTIQ TTL to the other source card and verify it remains
   active while Card B's 9.93 Hz contribution is gated off.
3. Test nearly coincident 9.93 Hz and ARTIQ pulses to determine whether both are
   recognized or merged by the trigger system.
4. Measure trigger-to-output latency and card-to-card timing skew on a scope.
5. Test long-running DDS queue refill/streaming under the intended trigger rates.
6. Test the external 10 MHz clock input and clock/trigger behavior together.
