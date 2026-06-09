"""Test a 10 MHz external reference clock on the M2p.6533 StarHub stack.

Wiring:
  10 MHz sine reference -> StarHub carrier/master clock input

For the current two-card stack, the StarHub carrier card is /dev/spcm1. The
StarHub distributes clock and trigger information to all enabled cards, so the
external reference is connected to the carrier/master clock input, not to EXT0
or an XIO trigger input.

Conservative electrical defaults for a low-voltage sine reference:
  - high-impedance clock input, so the source is not immediately loaded by 50 ohm;
  - 0 mV clock threshold, suitable for an AC-coupled or zero-centered sine;
  - 10 MHz reference frequency written before the sample rate;
  - small DDS output amplitude, only to prove synchronized operation.

Use --clock-termination-50ohm only when the reference source is specified and
configured to drive a 50 ohm load at the desired clock-input amplitude.
"""

import argparse
import time
from collections.abc import Callable

import spcm
from spcm import units


CARD_IDENTIFIERS: list[str] = ["/dev/spcm0", "/dev/spcm1"]
SYNC_IDENTIFIER: str = "sync0"
CARRIER_CARD_IDENTIFIER: str = "/dev/spcm1"


def print_sync_info(stack: spcm.CardStack) -> None:
    """Print StarHub membership and identify the carrier/master card."""
    sync = stack.sync
    sync_count = sync.sync_count()
    print(f"StarHub connectors: {sync.num_connectors()}")
    print(f"StarHub synced cards: {sync_count}")
    print(f"StarHub carrier index: {stack.sync_id} ({CARD_IDENTIFIERS[stack.sync_id]})")
    for sync_index in range(sync_count):
        print(
            f"  sync index {sync_index}: card index {sync.card_index(sync_index)}, "
            f"cable connector {sync.cable_connection(sync_index)}"
        )


def read_optional(label: str, getter: Callable[[], int | float]) -> str:
    """Return a printable hardware readback, including unsupported registers."""
    try:
        return str(getter())
    except Exception as exc:  # noqa: BLE001 - diagnostics should not mask the test.
        return f"unavailable ({exc})"


def q_to_float(value: object) -> float:
    """Convert a pint quantity or plain number to float for simple comparisons."""
    return float(getattr(value, "magnitude", value))


def print_clock_capabilities(card: spcm.Card, clock: spcm.Clock, prefix: str) -> None:
    """Print the clock input ranges and current configuration for one card."""
    print(f"{prefix} clock capabilities/readback:")
    print(f"  min external reference: {read_optional('', lambda: card.get_i(spcm.SPC_MIINST_MINEXTREFCLOCK))} Hz")
    print(f"  max external reference: {read_optional('', lambda: card.get_i(spcm.SPC_MIINST_MAXEXTREFCLOCK))} Hz")
    print(f"  threshold min:          {read_optional('', lambda: clock.threshold_min(return_unit=units.mV))}")
    print(f"  threshold max:          {read_optional('', lambda: clock.threshold_max(return_unit=units.mV))}")
    print(f"  threshold step:         {read_optional('', lambda: clock.threshold_step(return_unit=units.mV))}")
    print(f"  mode:                   0x{clock.mode():x}")
    print(f"  reference clock:        {clock.reference_clock()} Hz")
    print(f"  sample rate:            {clock.sample_rate(return_unit=units.Hz)}")
    print(f"  clock termination:      {'50 ohm' if clock.termination() else 'high impedance'}")
    print(f"  threshold:              {clock.threshold(return_unit=units.mV)}")
    print(f"  clock output enabled:   {bool(clock.clock_output())}")
    print(f"  PLL locked:             {read_optional('', lambda: card.get_i(spcm.SPC_PLL_ISLOCKED))}")
    print(f"  card status:            0x{card.status():x}")


def configure_external_reference(card: spcm.Card, args: argparse.Namespace) -> spcm.Clock:
    """Configure the carrier card for PLL mode locked to the external reference."""
    clock = spcm.Clock(card)

    print("Carrier clock capabilities before configuration:")
    print(f"  min external reference: {read_optional('', lambda: card.get_i(spcm.SPC_MIINST_MINEXTREFCLOCK))} Hz")
    print(f"  max external reference: {read_optional('', lambda: card.get_i(spcm.SPC_MIINST_MAXEXTREFCLOCK))} Hz")
    print(f"  threshold min:          {read_optional('', lambda: clock.threshold_min(return_unit=units.mV))}")
    print(f"  threshold max:          {read_optional('', lambda: clock.threshold_max(return_unit=units.mV))}")
    print(f"  threshold step:         {read_optional('', lambda: clock.threshold_step(return_unit=units.mV))}")

    min_ref = card.get_i(spcm.SPC_MIINST_MINEXTREFCLOCK)
    max_ref = card.get_i(spcm.SPC_MIINST_MAXEXTREFCLOCK)
    if not min_ref <= args.reference_hz <= max_ref:
        raise ValueError(
            f"Requested reference {args.reference_hz:g} Hz is outside the card readback range "
            f"{min_ref:g} Hz to {max_ref:g} Hz."
        )

    threshold_min = q_to_float(clock.threshold_min(return_unit=units.mV))
    threshold_max = q_to_float(clock.threshold_max(return_unit=units.mV))
    if not threshold_min <= args.clock_threshold_mv <= threshold_max:
        raise ValueError(
            f"Requested threshold {args.clock_threshold_mv:g} mV is outside the card readback range "
            f"{threshold_min:g} mV to {threshold_max:g} mV."
        )

    clock.mode(spcm.SPC_CM_EXTREFCLOCK)
    clock.reference_clock(args.reference_hz * units.Hz)
    clock.termination(args.clock_termination_50ohm)
    clock.threshold(args.clock_threshold_mv * units.mV)
    sample_rate = clock.sample_rate(clock.max_sample_rate(return_unit=units.Hz), return_unit=units.Hz)
    clock.clock_output(False)

    print("")
    print("Requested carrier external-reference configuration:")
    print(f"  reference:       {args.reference_hz:g} Hz")
    print(f"  sample rate:     {sample_rate}")
    print(f"  termination:     {'50 ohm' if args.clock_termination_50ohm else 'high impedance'}")
    print(f"  threshold:       {args.clock_threshold_mv:g} mV")
    print("  clock output:    disabled")
    return clock


def configure_trigger(card: spcm.Card, is_software_source: bool) -> spcm.Trigger:
    """Configure a single StarHub software trigger source."""
    trigger = spcm.Trigger(card)
    trigger.or_mask(spcm.SPC_TMASK_SOFTWARE if is_software_source else spcm.SPC_TMASK_NONE)
    trigger.and_mask(spcm.SPC_TMASK_NONE)
    return trigger


def configure_dds_card(
    card: spcm.Card,
    card_index: int,
    args: argparse.Namespace,
    is_software_source: bool,
) -> tuple[spcm.DDS, spcm.Trigger]:
    """Configure one card for a minimal synchronized DDS trigger-consumption test."""
    if card.function_type() != spcm.SPCM_TYPE_AO:
        raise spcm.SpcmException(f"{card} is not an analog output card.")

    print("")
    print(f"Configuring card {card_index}: {card}")
    print(f"  features: 0x{card.features():x}, ext_features: 0x{card.ext_features():x}")

    card.card_mode(spcm.SPC_REP_STD_DDS)

    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0)
    channels.enable(True)
    channels.output_load(50 * units.ohm)
    channels.amp(args.card_amp_v * units.V)

    trigger = configure_trigger(card, is_software_source=is_software_source)
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

    for step_index in range(1, args.armed_triggers + 1):
        dds[0].phase((step_index * args.triggered_phase_deg) % 360 * units.degrees)
        dds.exec_at_trg()
    dds.write_to_card()

    print(f"  trigger OR mask:          0x{trigger.or_mask():x}")
    print(f"  trigger AND mask:         0x{trigger.and_mask():x}")
    print(f"  DDS core 0 frequency:     {dds[0].get_freq(return_unit=units.Hz)}")
    print(f"  DDS core 0 amplitude:     {dds[0].get_amp(return_unit=units.mV)}")
    print(f"  armed DDS trigger updates:{args.armed_triggers}")
    print(f"  DDS queue count armed:    {dds.queue_cmd_count()}")
    return dds, trigger


def mute_dds(dds_units: list[spcm.DDS]) -> None:
    """Mute core 0 on each configured DDS card."""
    for card_index, dds in enumerate(dds_units):
        try:
            dds[0].amp(0)
            dds.exec_now()
            dds.write_to_card()
        except Exception as exc:  # noqa: BLE001 - preserve shutdown after clock-lock failures.
            print(f"  warning: could not mute card {card_index} DDS core 0 cleanly: {exc}")


def run_test(args: argparse.Namespace) -> None:
    """Configure the external reference and run a minimal synchronized DDS test."""
    print("Required wiring:")
    print("  10 MHz sine reference -> StarHub carrier/master clock input")
    print(f"  expected carrier: {CARRIER_CARD_IDENTIFIER}")
    print("  leave EXT0/XIO trigger inputs quiet for this test")
    print("")
    print("Conservative low-voltage defaults:")
    print(f"  clock input termination: {'50 ohm' if args.clock_termination_50ohm else 'high impedance'}")
    print(f"  clock threshold:         {args.clock_threshold_mv:g} mV")
    print(f"  DDS output amplitude:    {args.amp_mv:g} mV")
    if not args.no_prompt:
        input("Press Enter after the external reference is connected and running...")

    with spcm.CardStack(
        card_identifiers=CARD_IDENTIFIERS,
        sync_identifier=SYNC_IDENTIFIER,
        find_sync=True,
    ) as stack:
        print_sync_info(stack)
        if stack.sync_id < 0:
            raise SystemExit("FAIL: no StarHub carrier card was found.")
        if CARD_IDENTIFIERS[stack.sync_id] != CARRIER_CARD_IDENTIFIER:
            raise SystemExit(
                f"FAIL: expected carrier {CARRIER_CARD_IDENTIFIER}, "
                f"but CardStack reports {CARD_IDENTIFIERS[stack.sync_id]}."
            )

        carrier = stack.cards[stack.sync_id]
        carrier_clock = configure_external_reference(carrier, args)

        dds_units: list[spcm.DDS] = []
        triggers: list[spcm.Trigger] = []
        try:
            for card_index, card in enumerate(stack.cards):
                dds, trigger = configure_dds_card(
                    card,
                    card_index,
                    args,
                    is_software_source=(card_index == stack.sync_id),
                )
                dds_units.append(dds)
                triggers.append(trigger)

            print("")
            print_clock_capabilities(carrier, carrier_clock, "Carrier after write_setup")

            pll_lock_text = read_optional("", lambda: carrier.get_i(spcm.SPC_PLL_ISLOCKED))
            try:
                pll_locked = int(pll_lock_text.split()[0]) == 1
            except ValueError:
                pll_locked = False
            if not pll_locked:
                print("")
                print("WARNING: carrier PLL did not report locked after external-reference setup.")
                print("Continuing to test whether the synchronized DDS stack can still start and trigger.")

            enable_mask = stack.sync_enable(True)
            print("")
            print(f"StarHub enable mask: 0x{enable_mask:x}")

            queue_before = [dds.queue_cmd_count() for dds in dds_units]
            trig_before = [trigger.trigger_counter() for trigger in triggers]
            print(f"DDS queue counts before trigger: {queue_before}")
            print(f"Trigger counters before trigger: {trig_before}")

            try:
                stack.start(spcm.M2CMD_CARD_ENABLETRIGGER)
            except Exception as exc:  # noqa: BLE001 - collect per-card driver errors.
                print("")
                print(f"Stack start failed: {exc}")
                for card_index, card in enumerate(stack.cards):
                    last_error = getattr(card, "_last_error", None)
                    if last_error is not None:
                        print(f"  card {card_index} last driver error: {last_error}")
                raise SystemExit(
                    "FAIL: synchronized stack could not start with the external-reference "
                    "clock configuration."
                ) from None
            time.sleep(args.settle_s)
            stack.force_trigger()
            time.sleep(args.settle_s)

            queue_after = [dds.queue_cmd_count() for dds in dds_units]
            trig_after = [trigger.trigger_counter() for trigger in triggers]
            consumed = [before - after for before, after in zip(queue_before, queue_after)]
            triggered = [after - before for before, after in zip(trig_before, trig_after)]

            print(f"DDS queue counts after trigger:  {queue_after}")
            print(f"Trigger counters after trigger:  {trig_after}")
            print(f"DDS commands consumed:           {consumed}")
            print(f"Trigger counter deltas:          {triggered}")

            if not consumed or consumed[0] <= 0 or len(set(consumed)) != 1:
                raise SystemExit(
                    "FAIL: both DDS queues did not consume the same positive number of commands."
                )
            if not pll_locked:
                raise SystemExit(
                    "FAIL: synchronized DDS trigger path ran, but the carrier PLL did not report "
                    "external-reference lock."
                )

            print("")
            print("PASS: external 10 MHz reference locked the carrier and the StarHub DDS stack ran.")
            time.sleep(max(args.duration_s, 0.0))
        finally:
            print("Stopping synchronized DDS output and muting core 0.")
            try:
                stack.stop()
            except Exception as exc:  # noqa: BLE001 - stop can fail if start failed before locking.
                print(f"  warning: stack stop returned: {exc}")
            finally:
                mute_dds(dds_units)


def main() -> None:
    """Parse arguments and run the external-reference StarHub test."""
    parser = argparse.ArgumentParser(
        description="Test low-voltage 10 MHz external-reference clock on the M2p.6533 StarHub stack."
    )
    parser.add_argument("--no-prompt", action="store_true")
    parser.add_argument("--reference-hz", type=float, default=10_000_000.0)
    parser.add_argument("--clock-threshold-mv", type=float, default=0.0)
    parser.add_argument("--clock-termination-50ohm", action="store_true")
    parser.add_argument("--settle-s", type=float, default=0.25)
    parser.add_argument("--duration-s", type=float, default=1.0)
    parser.add_argument("--freq-hz", type=float, default=300_000.0)
    parser.add_argument("--amp-mv", type=float, default=20.0)
    parser.add_argument("--card-amp-v", type=float, default=0.5)
    parser.add_argument("--triggered-phase-deg", type=float, default=90.0)
    parser.add_argument("--armed-triggers", type=int, default=8)
    args = parser.parse_args()

    if args.reference_hz <= 0:
        raise ValueError("--reference-hz must be positive.")
    if args.settle_s < 0 or args.duration_s < 0:
        raise ValueError("--settle-s and --duration-s cannot be negative.")
    if args.amp_mv < 0 or args.card_amp_v <= 0:
        raise ValueError("Output amplitudes must be non-negative, with a positive channel range.")
    if args.armed_triggers < 1:
        raise ValueError("--armed-triggers must be at least 1.")

    run_test(args)


if __name__ == "__main__":
    main()
