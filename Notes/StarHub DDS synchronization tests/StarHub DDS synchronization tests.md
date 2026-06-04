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
| Test actual XIO trigger source | Pending | StarHub routing is validated, but the final XIO-to-Trig-In source still needs a loopback test. |
| Test actual ARTIQ trigger source | Pending | StarHub routing is validated, but the final ARTIQ TTL source still needs testing. |
| Test external 10 MHz clock input | Pending | Not covered by these tests. |
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

## Test scripts

- `src/examples/05_synchronization/5_sync_dds.py`
  - DDS-mode StarHub smoke test.
- `src/examples/05_synchronization/8_sync_dds_ext0_trigger_or.py`
  - Final simultaneous physical EXT0 OR test.
- `src/examples/05_synchronization/9_sync_dds_ext0_trigger_sources.py`
  - One-source-at-a-time physical EXT0 diagnostic.
- `src/examples/03_dds/09_dds_external_trigger.py`
  - Single-card physical EXT0 reference test.

## Next hardware tests

1. Replace the laboratory trigger source with XIO-to-Trig-In loopback and verify
   the same queue/counter behavior.
2. Connect the intended ARTIQ TTL to the other Trig In and verify OR behavior
   with the actual two-source hardware.
3. Test nearly coincident XIO and ARTIQ pulses to determine whether both are
   recognized or merged by the trigger system.
4. Measure trigger-to-output latency and card-to-card timing skew on a scope.
5. Test long-running DDS queue refill/streaming under the intended trigger rates.
6. Test the external 10 MHz clock input and clock/trigger behavior together.
