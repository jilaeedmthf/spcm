"""Validate a gated XIO trigger source distributed through StarHub.

Wiring:
  function generator 9.93 Hz TTL output -> /dev/spcm0 X1
  /dev/spcm0 X0 asynchronous output    -> /dev/spcm0 X2

The local trigger engine on spcm0 implements:

  OR mask:  EXT1 / physical X1, positive-edge mode
  AND mask: EXT2 / physical X2, HIGH-level mode

Therefore spcm0 contributes this event to StarHub:

  rising_edge(X1) AND X2_HIGH

X0 is changed through the asynchronous XIO register while the cards remain
running. Its physical loopback to X2 opens and closes the gate without changing
the trigger configuration. spcm1 has no local trigger source, but it remains in
the StarHub enable mask and receives every accepted spcm0 trigger.

The full test verifies:

1. Gate LOW: the continuous X1 input does not trigger either DDS card.
2. Gate HIGH: X1 rising edges trigger both DDS cards equally.
3. Gate LOW again: X1 rising edges stop triggering both cards.

No PulseGen firmware option is required for the gating card.
"""

import argparse
import time

import spcm
from spcm import units


CARD_IDENTIFIERS: list[str] = ["/dev/spcm0", "/dev/spcm1"]
SYNC_IDENTIFIER: str = "sync0"

# spcm0 owns the gated 9.93 Hz source. Other cards only receive StarHub events.
GATE_CARD_INDEX: int = 0

# Physical XIO assignments on spcm0.
GATE_OUTPUT_XIO: int = 0
SIGNAL_INPUT_XIO: int = 1
GATE_INPUT_XIO: int = 2


def has_bits(value: int, required: int) -> bool:
    """Return whether every bit in ``required`` is present in ``value``."""
    return value & required == required


def print_sync_info(stack: spcm.CardStack) -> None:
    """Print StarHub membership and physical cable-connector mapping."""
    sync = stack.sync
    sync_count = sync.sync_count()
    print(f"StarHub connectors: {sync.num_connectors()}")
    print(f"StarHub synced cards: {sync_count}")
    for sync_index in range(sync_count):
        print(
            f"  sync index {sync_index}: card index {sync.card_index(sync_index)}, "
            f"cable connector {sync.cable_connection(sync_index)}"
        )


def capability_probe(card: spcm.Card) -> bool:
    """Check that the card can implement ``rising_edge(X1) AND X2_HIGH``.

    Spectrum names the front-panel X1 and X2 trigger sources EXT1 and EXT2 in
    the trigger-mask and trigger-mode registers. This probe checks both layers:
    the XIO connectors must support trigger-input mode, and their corresponding
    EXT trigger sources must support the required OR/AND modes.

    Returns:
        ``True`` only when every required capability is reported by the card.
    """
    multi_ios = spcm.MultiPurposeIOs(card)
    available_or = card.get_i(spcm.SPC_TRIG_AVAILORMASK)
    available_and = card.get_i(spcm.SPC_TRIG_AVAILANDMASK)
    ext1_or_modes = card.get_i(spcm.SPC_TRIG_EXT1_AVAILMODESOR)
    ext2_and_modes = card.get_i(spcm.SPC_TRIG_EXT2_AVAILMODESAND)

    checks: list[tuple[str, bool]] = [
        (
            "X0 supports asynchronous output",
            has_bits(multi_ios[GATE_OUTPUT_XIO].avail_modes(), spcm.SPCM_XMODE_ASYNCOUT),
        ),
        (
            "X1 supports trigger input",
            has_bits(multi_ios[SIGNAL_INPUT_XIO].avail_modes(), spcm.SPCM_XMODE_TRIGIN),
        ),
        (
            "X2 supports trigger input",
            has_bits(multi_ios[GATE_INPUT_XIO].avail_modes(), spcm.SPCM_XMODE_TRIGIN),
        ),
        (
            "X1/EXT1 is available in trigger OR mask",
            has_bits(available_or, spcm.SPC_TMASK_EXT1),
        ),
        (
            "X2/EXT2 is available in trigger AND mask",
            has_bits(available_and, spcm.SPC_TMASK_EXT2),
        ),
        (
            "X1/EXT1 positive-edge mode is available in OR mask",
            has_bits(ext1_or_modes, spcm.SPC_TM_POS),
        ),
        (
            "X2/EXT2 HIGH-level mode is available in AND mask",
            has_bits(ext2_and_modes, spcm.SPC_TM_HIGH),
        ),
    ]

    print(f"Found gate card: {card}")
    print(f"  features: 0x{card.features():x}, ext_features: 0x{card.ext_features():x}")
    print(f"  available trigger OR mask:  0x{available_or:x}")
    print(f"  available trigger AND mask: 0x{available_and:x}")
    for xio_index, multi_io in enumerate(multi_ios):
        print(f"  X{xio_index} available modes: 0x{multi_io.avail_modes():x}")
    print(f"  X1/EXT1 available OR modes:  0x{ext1_or_modes:x}")
    print(f"  X2/EXT2 available AND modes: 0x{ext2_and_modes:x}")
    print("")
    print("Required capability checks:")
    for description, passed in checks:
        print(f"  {'PASS' if passed else 'FAIL'}: {description}")

    return all(passed for _, passed in checks)


def configure_gate_trigger(card: spcm.Card) -> tuple[spcm.Trigger, spcm.MultiPurposeIOs]:
    """Configure spcm0's local XIO gate and return its control objects.

    X0 is an asynchronous output. A short physical cable loops X0 into X2, so
    software can change the X2 gate level while the card remains running.

    X1 and X2 are configured as trigger inputs. In the trigger engine, X1 maps
    to EXT1 and X2 maps to EXT2:

        local trigger = EXT1 positive edge AND EXT2 HIGH

    The accepted local trigger is then contributed to the StarHub group.
    """
    multi_ios = spcm.MultiPurposeIOs(card)
    multi_ios[GATE_OUTPUT_XIO].x_mode(spcm.SPCM_XMODE_ASYNCOUT)
    multi_ios[SIGNAL_INPUT_XIO].x_mode(spcm.SPCM_XMODE_TRIGIN)
    multi_ios[GATE_INPUT_XIO].x_mode(spcm.SPCM_XMODE_TRIGIN)
    multi_ios.asyncio(0)

    trigger = spcm.Trigger(card)
    trigger.or_mask(spcm.SPC_TMASK_EXT1)
    trigger.and_mask(spcm.SPC_TMASK_EXT2)
    trigger.ext1_mode(spcm.SPC_TM_POS)
    # The high-level Trigger wrapper exposes ext1_mode(), but not ext2_mode().
    card.set_i(spcm.SPC_TRIG_EXT2_MODE, spcm.SPC_TM_HIGH)

    print("Gate trigger configuration readback:")
    print(f"  X0 mode:               0x{multi_ios[0].x_mode():x} (ASYNCOUT)")
    print(f"  X1 mode:               0x{multi_ios[1].x_mode():x} (TRIGIN)")
    print(f"  X2 mode:               0x{multi_ios[2].x_mode():x} (TRIGIN)")
    print(f"  trigger OR mask:       0x{trigger.or_mask():x} (EXT1)")
    print(f"  trigger AND mask:      0x{trigger.and_mask():x} (EXT2)")
    print(f"  X1/EXT1 trigger mode:  0x{trigger.ext1_mode():x} (positive edge)")
    print(
        f"  X2/EXT2 trigger mode:  "
        f"0x{card.get_i(spcm.SPC_TRIG_EXT2_MODE):x} (HIGH level)"
    )
    return trigger, multi_ios


def configure_dds_card(
    card: spcm.Card,
    card_index: int,
    args: argparse.Namespace,
) -> tuple[spcm.DDS, spcm.Trigger, spcm.MultiPurposeIOs | None]:
    """Configure one card as either the gated source or a StarHub receiver.

    The gated source card contributes its accepted local XIO trigger. Receiver
    cards use local trigger mask NONE: they contribute nothing locally, but
    still receive the distributed trigger because they are enabled in StarHub.

    An initial DDS state is executed immediately. Later phase updates are queued
    with ``exec_at_trg()`` so each accepted StarHub event consumes one command.
    Equal queue consumption across cards is the primary proof that their DDS
    engines executed the same synchronized events.

    Returns:
        The configured DDS and trigger objects, plus the source card's XIO
        controller. The XIO controller is ``None`` for receiver cards.
    """
    if card.function_type() != spcm.SPCM_TYPE_AO:
        raise spcm.SpcmException(f"{card} is not an analog output card.")

    print("")
    print(f"Found card {card_index}: {card}")
    card.card_mode(spcm.SPC_REP_STD_DDS)

    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0)
    channels.enable(True)
    channels.output_load(50 * units.ohm)
    channels.amp(args.card_amp_v * units.V)

    gate_ios: spcm.MultiPurposeIOs | None = None
    if card_index == GATE_CARD_INDEX:
        trigger, gate_ios = configure_gate_trigger(card)
    else:
        trigger = spcm.Trigger(card)
        trigger.or_mask(spcm.SPC_TMASK_NONE)
        trigger.and_mask(spcm.SPC_TMASK_NONE)
        print("Receiver trigger configuration:")
        print(f"  trigger OR mask:  0x{trigger.or_mask():x} (NONE)")
        print(f"  trigger AND mask: 0x{trigger.and_mask():x} (NONE)")

    # Apply card/XIO/trigger configuration before initializing the DDS queue.
    card.write_setup()

    dds = spcm.DDS(card, channels=channels, check_features=True)
    dds.reset()
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)
    dds.phase_behaviour(spcm.SPCM_DDS_PHASE_JUMP)
    dds[0].amp(args.amp_mv * units.mV)
    dds[0].freq(args.freq_hz * units.Hz)
    dds[0].phase(0 * units.degrees)
    dds.exec_now()
    dds.write_to_card()

    # Leave one queue slot free and arm identical updates on every card.
    armed_triggers = min(args.armed_triggers, dds.queue_cmd_max() - 1)
    for phase_index in range(1, armed_triggers + 1):
        dds[0].phase((phase_index * args.phase_step_deg) % 360 * units.degrees)
        dds.exec_at_trg()
    dds.write_to_card()

    print(f"  DDS queue maximum: {dds.queue_cmd_max()}")
    print(f"  armed DDS trigger updates: {armed_triggers}")
    print(f"  DDS queue count before start: {dds.queue_cmd_count()}")
    return dds, trigger, gate_ios


def queue_counts(dds_units: list[spcm.DDS]) -> list[int]:
    """Return the number of commands currently waiting in each DDS queue."""
    return [dds.queue_cmd_count() for dds in dds_units]


def trigger_counts(triggers: list[spcm.Trigger]) -> list[int]:
    """Return each card trigger engine's event counter."""
    return [trigger.trigger_counter() for trigger in triggers]


def print_counts(
    label: str,
    trigger_values: list[int],
    queue_values: list[int],
) -> None:
    """Print trigger-engine and DDS-queue counters together for each card."""
    print(label)
    for card_index, (trigger_value, queue_value) in enumerate(zip(trigger_values, queue_values)):
        print(
            f"  card {card_index}: trigger counter={trigger_value}, "
            f"DDS queue count={queue_value}"
        )


def measure_window(
    label: str,
    duration_s: float,
    dds_units: list[spcm.DDS],
    triggers: list[spcm.Trigger],
) -> tuple[list[int], list[int]]:
    """Measure trigger events and DDS command consumption during a time window.

    Returns:
        Two per-card delta lists: trigger-counter increases and DDS commands
        consumed. Queue consumption is reported as a positive number.
    """
    before_triggers = trigger_counts(triggers)
    before_queues = queue_counts(dds_units)
    time.sleep(duration_s)
    after_triggers = trigger_counts(triggers)
    after_queues = queue_counts(dds_units)

    trigger_deltas = [after - before for before, after in zip(before_triggers, after_triggers)]
    queue_consumed = [before - after for before, after in zip(before_queues, after_queues)]
    print_counts(f"{label} after {duration_s:g} s:", after_triggers, after_queues)
    print(f"  trigger counter deltas: {trigger_deltas}")
    print(f"  DDS commands consumed:  {queue_consumed}")
    return trigger_deltas, queue_consumed


def all_zero(values: list[int]) -> bool:
    """Return whether every measured delta is zero."""
    return all(value == 0 for value in values)


def all_equal_positive(values: list[int]) -> bool:
    """Return whether all cards report the same positive delta."""
    return bool(values) and values[0] > 0 and len(set(values)) == 1


def set_async_gate(multi_ios: spcm.MultiPurposeIOs, enabled: bool, settle_s: float) -> None:
    """Set physical X0 and verify the resulting gate level through X2.

    On this M2p.6533, the asynchronous readback bit for output X0 does not
    reliably show its physical output state. The looped-back X2 input does, so
    X2 is the authoritative gate-state readback.

    Raises:
        RuntimeError: If looped-back X2 does not match the requested X0 state.
    """
    output_mask = 1 << GATE_OUTPUT_XIO if enabled else 0
    multi_ios.asyncio(output_mask)
    time.sleep(settle_s)
    state = multi_ios.asyncio()
    loopback_high = bool(state & (1 << GATE_INPUT_XIO))
    print(
        f"Set X0 gate {'HIGH' if enabled else 'LOW'}; "
        f"looped-back X2 is {'HIGH' if loopback_high else 'LOW'} (state=0x{state:x})."
    )
    if loopback_high != enabled:
        raise RuntimeError("Looped-back X2 state does not match the requested X0 gate state.")


def run_probe_only() -> None:
    """Check and apply the XIO gate configuration without starting the cards."""
    with spcm.Card(CARD_IDENTIFIERS[GATE_CARD_INDEX]) as card:
        card.card_mode(spcm.SPC_REP_STD_DDS)
        if not capability_probe(card):
            raise SystemExit("FAIL: spcm0 does not report every capability required by the XIO gate.")

        configure_gate_trigger(card)
        card.write_setup()
        print("")
        print("PASS: spcm0 accepted the XIO trigger-engine gate configuration.")


def run_async_output_probe(input_xio: int) -> None:
    """Toggle X0 LOW/HIGH/LOW and verify it through a selected loopback input.

    This stopped-card electrical diagnostic isolates the X0 output, cable, and
    selected XIO input from the trigger engine and StarHub.
    """
    with spcm.Card(CARD_IDENTIFIERS[GATE_CARD_INDEX]) as card:
        multi_ios = spcm.MultiPurposeIOs(card)
        multi_ios[GATE_OUTPUT_XIO].x_mode(spcm.SPCM_XMODE_ASYNCOUT)
        multi_ios[input_xio].x_mode(spcm.SPCM_XMODE_ASYNCIN)
        card.write_setup()

        print(f"Stopped-card X0 -> X{input_xio} asynchronous loopback probe:")
        passed = True
        for enabled in (False, True, False):
            requested = 1 << GATE_OUTPUT_XIO if enabled else 0
            state = multi_ios.asyncio(requested)
            time.sleep(0.1)
            state = multi_ios.asyncio()
            # X0 readback is printed for context but is not used as pass/fail.
            x0_high = bool(state & (1 << GATE_OUTPUT_XIO))
            input_high = bool(state & (1 << input_xio))
            print(
                f"  requested X0 {'HIGH' if enabled else 'LOW'}: "
                f"state=0x{state:x}, X0={'HIGH' if x0_high else 'LOW'}, "
                f"X{input_xio}={'HIGH' if input_high else 'LOW'}"
            )
            passed &= input_high == enabled

        if not passed:
            raise SystemExit(
                f"FAIL: stopped-card X0 -> X{input_xio} asynchronous loopback did not follow."
            )
        print(f"PASS: stopped-card X{input_xio} loopback follows requested X0 LOW/HIGH/LOW.")


def run_signal_input_probe(duration_s: float) -> None:
    """Poll X1 asynchronously to verify that an external square wave is present.

    This is a wiring/electrical diagnostic, not a precision frequency counter.
    The 1 ms polling interval is sufficient for the intended 9.93/10 Hz input.
    """
    with spcm.Card(CARD_IDENTIFIERS[GATE_CARD_INDEX]) as card:
        multi_ios = spcm.MultiPurposeIOs(card)
        multi_ios[SIGNAL_INPUT_XIO].x_mode(spcm.SPCM_XMODE_ASYNCIN)
        card.write_setup()

        deadline = time.monotonic() + duration_s
        previous = None
        rising_edges = 0
        falling_edges = 0
        saw_low = False
        saw_high = False
        while time.monotonic() < deadline:
            state = multi_ios.asyncio()
            high = bool(state & (1 << SIGNAL_INPUT_XIO))
            saw_low |= not high
            saw_high |= high
            if previous is not None:
                rising_edges += not previous and high
                falling_edges += previous and not high
            previous = high
            time.sleep(0.001)

        print(f"X1 input probe over {duration_s:g} s:")
        print(f"  saw LOW:  {'YES' if saw_low else 'NO'}")
        print(f"  saw HIGH: {'YES' if saw_high else 'NO'}")
        print(f"  sampled rising edges:  {rising_edges}")
        print(f"  sampled falling edges: {falling_edges}")
        if not (saw_low and saw_high and rising_edges > 0 and falling_edges > 0):
            raise SystemExit("FAIL: X1 did not show a toggling square-wave input.")
        print("PASS: X1 shows a toggling square-wave input.")


def run_starhub_test(args: argparse.Namespace) -> None:
    """Run the complete synchronized LOW -> HIGH -> LOW XIO gate test.

    spcm0 contributes the gated X1 source. spcm1 contributes no local source,
    but both cards are armed through StarHub and must consume accepted events
    equally. The test changes only X0's asynchronous output state; it never
    stops or reconfigures the trigger engine between measurement windows.
    """
    print("Required wiring:")
    print("  function generator 9.93 Hz TTL output -> /dev/spcm0 X1")
    print("  /dev/spcm0 X0 asynchronous output    -> /dev/spcm0 X2")
    print("Use a TTL-compatible signal and leave other trigger inputs quiet.")
    if not args.no_prompt:
        input("Press Enter after the wiring is connected and the function generator is running...")

    with spcm.CardStack(
        card_identifiers=CARD_IDENTIFIERS,
        sync_identifier=SYNC_IDENTIFIER,
        find_sync=True,
    ) as stack:
        print_sync_info(stack)
        if not capability_probe(stack.cards[GATE_CARD_INDEX]):
            raise SystemExit("FAIL: spcm0 does not report every capability required by the XIO gate.")

        dds_units: list[spcm.DDS] = []
        triggers: list[spcm.Trigger] = []
        gate_ios: spcm.MultiPurposeIOs | None = None
        for card_index, card in enumerate(stack.cards):
            dds, trigger, configured_gate_ios = configure_dds_card(
                card,
                card_index,
                args,
            )
            dds_units.append(dds)
            triggers.append(trigger)
            if configured_gate_ios is not None:
                gate_ios = configured_gate_ios

        if gate_ios is None:
            raise RuntimeError("spcm0 gate XIO controller was not configured.")

        enable_mask = stack.sync_enable(True)
        print(f"StarHub enable mask: 0x{enable_mask:x}")
        print("")
        print("Starting synchronized DDS group with X0/X2 gate LOW.")

        results: dict[str, bool] = {}
        try:
            set_async_gate(gate_ios, False, args.settle_s)
            stack.start(spcm.M2CMD_CARD_ENABLETRIGGER)
            time.sleep(args.settle_s)

            low1_triggers, low1_queues = measure_window(
                "Initial gate LOW window",
                args.window_s,
                dds_units,
                triggers,
            )
            results["initial LOW blocks"] = all_zero(low1_triggers) and all_zero(low1_queues)

            print("")
            set_async_gate(gate_ios, True, args.settle_s)
            high_triggers, high_queues = measure_window(
                "Gate HIGH window",
                args.window_s,
                dds_units,
                triggers,
            )
            results["HIGH passes equally"] = (
                all_equal_positive(high_triggers)
                and all_equal_positive(high_queues)
                and high_triggers == high_queues
            )

            print("")
            set_async_gate(gate_ios, False, args.settle_s)
            low2_triggers, low2_queues = measure_window(
                "Final gate LOW window",
                args.window_s,
                dds_units,
                triggers,
            )
            results["final LOW blocks"] = all_zero(low2_triggers) and all_zero(low2_queues)
        finally:
            print("")
            print("Returning X0 gate LOW and stopping synchronized DDS output.")
            try:
                set_async_gate(gate_ios, False, args.settle_s)
            finally:
                stack.stop()

    print("")
    print("Results:")
    for description, passed in results.items():
        print(f"  {'PASS' if passed else 'FAIL'}: {description}")

    if all(results.values()):
        print("")
        print("PASS: asynchronous X0 gated spcm0's 10 Hz StarHub contribution.")
    else:
        raise SystemExit("FAIL: at least one XIO trigger-engine gate condition failed.")


def main() -> None:
    """Parse diagnostic/test options and run the selected operation."""
    parser = argparse.ArgumentParser(description="Test spcm0 XIO trigger-engine gating through StarHub.")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--async-output-probe", action="store_true")
    parser.add_argument("--loopback-input-xio", type=int, choices=(1, 2, 3), default=GATE_INPUT_XIO)
    parser.add_argument("--signal-input-probe", action="store_true")
    parser.add_argument("--no-prompt", action="store_true")
    parser.add_argument("--window-s", type=float, default=1.5)
    parser.add_argument("--settle-s", type=float, default=0.15)
    parser.add_argument("--armed-triggers", type=int, default=128)
    parser.add_argument("--freq-hz", type=float, default=300_000.0)
    parser.add_argument("--amp-mv", type=float, default=100.0)
    parser.add_argument("--card-amp-v", type=float, default=0.5)
    parser.add_argument("--phase-step-deg", type=float, default=45.0)
    args = parser.parse_args()

    if args.window_s <= 0 or args.settle_s < 0:
        raise ValueError("Measurement windows must be positive and settle time cannot be negative.")
    if args.armed_triggers < 8:
        raise ValueError("--armed-triggers must be at least 8.")

    if args.signal_input_probe:
        run_signal_input_probe(args.window_s)
    elif args.async_output_probe:
        run_async_output_probe(args.loopback_input_xio)
    elif args.probe_only:
        run_probe_only()
    else:
        run_starhub_test(args)


if __name__ == "__main__":
    main()
