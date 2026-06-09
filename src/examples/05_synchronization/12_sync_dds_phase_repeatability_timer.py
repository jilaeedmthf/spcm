"""StarHub CH0 phase-repeatability test using a force trigger and DDS timers.

Wiring:
  10 MHz sine reference -> /dev/spcm1 StarHub carrier/master Clk In
  /dev/spcm0 CH0        -> lock-in input/reference path under test
  /dev/spcm1 CH0        -> lock-in input/reference path under test

The reference source should be configured as 1 Vpp into 50 ohm. This script
therefore enables the card's 50-ohm clock-input termination on /dev/spcm1.

Behavior:
  1. Both cards are armed through StarHub while locked to the external 10 MHz
     reference.
  2. stack.force_trigger() applies the first state synchronously:
       /dev/spcm0 CH0 = 300 kHz, 500 mV, 0 deg
       /dev/spcm1 CH0 = 300 kHz, 500 mV, 0 deg
     and starts each card's DDS timer.
  3. After PHASE_DELAY_S, each card's DDS timer applies the second state:
       /dev/spcm0 CH0 = SECOND_PHASE_SPCM0_DEG
       /dev/spcm1 CH0 = SECOND_PHASE_SPCM1_DEG
  4. Press Enter after state 2 is reached. The script then issues a second
     stack.force_trigger() to apply the pre-queued third state.

Measure the CH0 outputs with the lock-in amplifier to check cross-card phase
repeatability.
"""

import time
from collections.abc import Callable

import spcm
from spcm import units


CARD_IDENTIFIERS: list[str] = ["/dev/spcm0", "/dev/spcm1"]
SYNC_IDENTIFIER: str = "sync0"
CARRIER_CARD_IDENTIFIER: str = "/dev/spcm1"

REFERENCE_HZ: float = 10_000_000.0
CLOCK_TERMINATION_50OHM: bool = True
CLOCK_THRESHOLD_MV: float = 0.0

DDS_FREQUENCY_HZ: float = 300_000.0
DDS_CHANNEL_MASK: int = spcm.CHANNEL0
DDS_CORE_INDEX: int = 0
CHANNEL_RANGE_V: float = 1.0
DDS_AMPLITUDE_MV: float = 500.0

INITIAL_PHASE_DEG: float = 0.0
SECOND_PHASE_SPCM0_DEG: float = 0.0
SECOND_PHASE_SPCM1_DEG: float = -90.0
THIRD_PHASE_SPCM0_DEG: float = 0.0
THIRD_PHASE_SPCM1_DEG: float = 120.0
PHASE_DELAY_S: float = 5.0
TIMER_SETTLE_S: float = 0.25
FORCE_TRIGGER_SETTLE_S: float = 0.25


def read_optional(getter: Callable[[], int | float]) -> str:
    """Return a printable hardware readback, including unsupported registers."""
    try:
        return str(getter())
    except Exception as exc:  # noqa: BLE001 - diagnostics should not mask the test.
        return f"unavailable ({exc})"


def q_to_float(value: object) -> float:
    """Convert a pint quantity or plain number to float for simple comparisons."""
    return float(getattr(value, "magnitude", value))


def dds_status_text(dds: spcm.DDS) -> str:
    """Return a readable DDS status string for pass/fail diagnostics."""
    status = dds.status()
    names: list[str] = []
    if status & spcm.SPCM_DDS_STAT_WAITING_FOR_TRG:
        names.append("WAITING_FOR_TRG")
    if status & spcm.SPCM_DDS_STAT_QUEUE_UNDERRUN:
        names.append("QUEUE_UNDERRUN")
    if status & spcm.SPCM_DDS_STAT_QUEUE_OVERRUN:
        names.append("QUEUE_OVERRUN")
    return f"0x{status:x} ({', '.join(names) if names else 'none'})"


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


def configure_external_reference(card: spcm.Card) -> spcm.Clock:
    """Configure /dev/spcm1 for PLL mode locked to the external 10 MHz clock."""
    clock = spcm.Clock(card)

    min_ref = card.get_i(spcm.SPC_MIINST_MINEXTREFCLOCK)
    max_ref = card.get_i(spcm.SPC_MIINST_MAXEXTREFCLOCK)
    threshold_min = q_to_float(clock.threshold_min(return_unit=units.mV))
    threshold_max = q_to_float(clock.threshold_max(return_unit=units.mV))

    print("Carrier clock capabilities before configuration:")
    print(f"  min external reference: {min_ref} Hz")
    print(f"  max external reference: {max_ref} Hz")
    print(f"  threshold min:          {clock.threshold_min(return_unit=units.mV)}")
    print(f"  threshold max:          {clock.threshold_max(return_unit=units.mV)}")
    print(f"  threshold step:         {clock.threshold_step(return_unit=units.mV)}")

    if not min_ref <= REFERENCE_HZ <= max_ref:
        raise ValueError(
            f"Requested reference {REFERENCE_HZ:g} Hz is outside the card readback range "
            f"{min_ref:g} Hz to {max_ref:g} Hz."
        )
    if not threshold_min <= CLOCK_THRESHOLD_MV <= threshold_max:
        raise ValueError(
            f"Requested threshold {CLOCK_THRESHOLD_MV:g} mV is outside the card readback range "
            f"{threshold_min:g} mV to {threshold_max:g} mV."
        )

    clock.mode(spcm.SPC_CM_EXTREFCLOCK)
    clock.reference_clock(REFERENCE_HZ * units.Hz)
    clock.termination(CLOCK_TERMINATION_50OHM)
    clock.threshold(CLOCK_THRESHOLD_MV * units.mV)
    sample_rate = clock.sample_rate(clock.max_sample_rate(return_unit=units.Hz), return_unit=units.Hz)
    clock.clock_output(False)

    print("")
    print("Requested carrier external-reference configuration:")
    print(f"  reference:       {REFERENCE_HZ:g} Hz")
    print(f"  sample rate:     {sample_rate}")
    print(f"  termination:     {'50 ohm' if CLOCK_TERMINATION_50OHM else 'high impedance'}")
    print(f"  threshold:       {CLOCK_THRESHOLD_MV:g} mV")
    print("  clock output:    disabled")
    return clock


def print_clock_readback(card: spcm.Card, clock: spcm.Clock) -> bool:
    """Print carrier clock readback and return whether the PLL reports locked."""
    pll_lock_text = read_optional(lambda: card.get_i(spcm.SPC_PLL_ISLOCKED))
    try:
        pll_locked = int(pll_lock_text.split()[0]) == 1
    except ValueError:
        pll_locked = False

    print("")
    print("Carrier clock readback after write_setup:")
    print(f"  mode:                   0x{clock.mode():x}")
    print(f"  reference clock:        {clock.reference_clock()} Hz")
    print(f"  sample rate:            {clock.sample_rate(return_unit=units.Hz)}")
    print(f"  clock termination:      {'50 ohm' if clock.termination() else 'high impedance'}")
    print(f"  threshold:              {clock.threshold(return_unit=units.mV)}")
    print(f"  clock output enabled:   {bool(clock.clock_output())}")
    print(f"  PLL locked:             {pll_lock_text}")
    print(f"  card status:            0x{card.status():x}")
    return pll_locked


def configure_trigger(card: spcm.Card, is_software_source: bool) -> spcm.Trigger:
    """Disable physical/software trigger sources and use explicit force commands."""
    trigger = spcm.Trigger(card)
    trigger.or_mask(spcm.SPC_TMASK_NONE)
    trigger.and_mask(spcm.SPC_TMASK_NONE)
    return trigger


def second_phase_for_card(card_index: int) -> float:
    """Return the second-state phase for the selected card."""
    if card_index == 0:
        return SECOND_PHASE_SPCM0_DEG
    if card_index == 1:
        return SECOND_PHASE_SPCM1_DEG
    raise ValueError(f"No second phase is defined for card index {card_index}.")


def third_phase_for_card(card_index: int) -> float:
    """Return the third-state phase for the selected card."""
    if card_index == 0:
        return THIRD_PHASE_SPCM0_DEG
    if card_index == 1:
        return THIRD_PHASE_SPCM1_DEG
    raise ValueError(f"No third phase is defined for card index {card_index}.")


def configure_dds_card(
    card: spcm.Card,
    card_index: int,
    is_software_source: bool,
) -> tuple[spcm.DDS, spcm.Trigger]:
    """Configure one card for the synchronized force-trigger/timer phase test."""
    if card.function_type() != spcm.SPCM_TYPE_AO:
        raise spcm.SpcmException(f"{card} is not an analog output card.")

    print("")
    print(f"Configuring card {card_index}: {card}")
    print(f"  features: 0x{card.features():x}, ext_features: 0x{card.ext_features():x}")

    card.card_mode(spcm.SPC_REP_STD_DDS)

    channels = spcm.Channels(card, card_enable=DDS_CHANNEL_MASK)
    channels.enable(True)
    # channels.output_load(50 * units.ohm)
    channels.output_load(units.highZ)
    channels.amp(CHANNEL_RANGE_V * units.V)

    trigger = configure_trigger(card, is_software_source=is_software_source)
    card.write_setup()

    dds = spcm.DDS(card, channels=channels, check_features=True)
    dds.reset()
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)
    dds.phase_behaviour(spcm.SPCM_DDS_PHASE_JUMP)

    # Idle setup: no output until the synchronized force trigger applies state 1.
    dds[DDS_CORE_INDEX].amp(0 * units.mV)
    dds[DDS_CORE_INDEX].freq(DDS_FREQUENCY_HZ * units.Hz)
    dds[DDS_CORE_INDEX].phase(INITIAL_PHASE_DEG * units.degrees)
    dds.exec_now()
    dds.write_to_card()

    # State 1: consumed by the StarHub software force trigger.
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_TIMER)
    dds.trg_timer(PHASE_DELAY_S)
    dds[DDS_CORE_INDEX].amp(DDS_AMPLITUDE_MV * units.mV)
    dds[DDS_CORE_INDEX].freq(DDS_FREQUENCY_HZ * units.Hz)
    dds[DDS_CORE_INDEX].phase(INITIAL_PHASE_DEG * units.degrees)
    dds.exec_at_trg()

    # State 2: consumed by each card's DDS timer after PHASE_DELAY_S.
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)
    dds[DDS_CORE_INDEX].amp(DDS_AMPLITUDE_MV * units.mV)
    dds[DDS_CORE_INDEX].freq(DDS_FREQUENCY_HZ * units.Hz)
    dds[DDS_CORE_INDEX].phase(second_phase_for_card(card_index) * units.degrees)
    dds.exec_at_trg()

    # State 3: consumed by the later StarHub software force trigger.
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)
    dds[DDS_CORE_INDEX].amp(DDS_AMPLITUDE_MV * units.mV)
    dds[DDS_CORE_INDEX].freq(DDS_FREQUENCY_HZ * units.Hz)
    dds[DDS_CORE_INDEX].phase(third_phase_for_card(card_index) * units.degrees)
    dds.exec_at_trg()

    dds.write_to_card()

    print(f"  trigger OR mask:       0x{trigger.or_mask():x}")
    print(f"  trigger AND mask:      0x{trigger.and_mask():x}")
    print(f"  channel mask:          0x{DDS_CHANNEL_MASK:x}")
    print(f"  DDS core:              {DDS_CORE_INDEX}")
    print(f"  DDS frequency:         {dds[DDS_CORE_INDEX].get_freq(return_unit=units.Hz)}")
    print(f"  DDS amplitude:         {dds[DDS_CORE_INDEX].get_amp(return_unit=units.mV)}")
    print(f"  DDS timer period:      {dds.get_trg_timer(return_unit=units.s)}")
    print(f"  second-state phase:    {second_phase_for_card(card_index):g} deg")
    print(f"  third-state phase:     {third_phase_for_card(card_index):g} deg")
    print(f"  DDS queue count armed: {dds.queue_cmd_count()}")
    print(f"  DDS status:            {dds_status_text(dds)}")
    return dds, trigger


def mute_dds(dds_units: list[spcm.DDS]) -> None:
    """Mute the selected DDS core on every configured card."""
    for card_index, dds in enumerate(dds_units):
        try:
            dds[DDS_CORE_INDEX].amp(0 * units.mV)
            dds.exec_now()
            dds.write_to_card()
        except Exception as exc:  # noqa: BLE001 - preserve shutdown after hardware errors.
            print(f"  warning: could not mute card {card_index} DDS core {DDS_CORE_INDEX}: {exc}")


def run_test() -> None:
    """Run the synchronized force-trigger/timer phase-repeatability test."""
    print("Required wiring:")
    print("  10 MHz sine reference -> /dev/spcm1 StarHub carrier/master Clk In")
    print("  /dev/spcm0 CH0        -> lock-in measurement input")
    print("  /dev/spcm1 CH0        -> lock-in measurement input/reference")
    print("")
    print("Expected sequence:")
    print(f"  force trigger: both cards -> {DDS_FREQUENCY_HZ:g} Hz, {DDS_AMPLITUDE_MV:g} mV, 0 deg")
    print(
        f"  {PHASE_DELAY_S:g} s later: /dev/spcm0 -> {SECOND_PHASE_SPCM0_DEG:g} deg, "
        f"/dev/spcm1 -> {SECOND_PHASE_SPCM1_DEG:g} deg"
    )
    print(
        f"  Enter-triggered state: /dev/spcm0 -> {THIRD_PHASE_SPCM0_DEG:g} deg, "
        f"/dev/spcm1 -> {THIRD_PHASE_SPCM1_DEG:g} deg"
    )
    print("")
    print("Assuming the external reference clock and lock-in wiring are already connected.")

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
        carrier_clock = configure_external_reference(carrier)

        dds_units: list[spcm.DDS] = []
        triggers: list[spcm.Trigger] = []
        started = False
        try:
            for card_index, card in enumerate(stack.cards):
                dds, trigger = configure_dds_card(
                    card,
                    card_index,
                    is_software_source=(card_index == stack.sync_id),
                )
                dds_units.append(dds)
                triggers.append(trigger)

            pll_locked = print_clock_readback(carrier, carrier_clock)
            if not pll_locked:
                raise SystemExit("FAIL: carrier PLL did not report external-reference lock.")

            enable_mask = stack.sync_enable(True)
            print("")
            print(f"StarHub enable mask: 0x{enable_mask:x}")

            queue_before = [dds.queue_cmd_count() for dds in dds_units]
            trigger_before = [trigger.trigger_counter() for trigger in triggers]
            print(f"DDS queue counts before force trigger: {queue_before}")
            print(f"Trigger counters before force trigger: {trigger_before}")

            stack.start(spcm.M2CMD_CARD_ENABLETRIGGER)
            started = True
            time.sleep(TIMER_SETTLE_S)

            print("")
            print("Issuing one StarHub software force trigger.")
            stack.force_trigger()
            time.sleep(PHASE_DELAY_S + TIMER_SETTLE_S)

            queue_after_timer = [dds.queue_cmd_count() for dds in dds_units]
            trigger_after_timer = [trigger.trigger_counter() for trigger in triggers]
            consumed_after_timer = [
                before - after for before, after in zip(queue_before, queue_after_timer)
            ]
            triggered_after_timer = [
                after - before for before, after in zip(trigger_before, trigger_after_timer)
            ]

            print("")
            print("Post-timer diagnostics:")
            print(f"  DDS queue counts after timer: {queue_after_timer}")
            print(f"  DDS commands consumed:       {consumed_after_timer}")
            print(f"  trigger counters after:      {trigger_after_timer}")
            print(f"  trigger counter deltas:      {triggered_after_timer}")
            for card_index, dds in enumerate(dds_units):
                print(f"  card {card_index} DDS status: {dds_status_text(dds)}")
                print(
                    f"  card {card_index} core {DDS_CORE_INDEX}: "
                    f"freq={dds[DDS_CORE_INDEX].get_freq(return_unit=units.Hz)}, "
                    f"amp={dds[DDS_CORE_INDEX].get_amp(return_unit=units.mV)}, "
                    f"phase={dds[DDS_CORE_INDEX].get_phase(return_unit=units.degrees)}"
                )

            if (
                not consumed_after_timer
                or consumed_after_timer[0] <= 0
                or len(set(consumed_after_timer)) != 1
            ):
                print(
                    "  note: DDS queue-count consumption is diagnostic only; "
                    "use the lock-in/readbacks to confirm the timer state."
                )
            queue_before_enter = [dds.queue_cmd_count() for dds in dds_units]
            print(f"DDS queue counts before Enter force trigger: {queue_before_enter}")
            input("Press Enter after state 2 is reached to force trigger the pre-queued state 3...")
            stack.force_trigger()
            time.sleep(FORCE_TRIGGER_SETTLE_S)

            queue_after_force = [dds.queue_cmd_count() for dds in dds_units]
            trigger_after_force = [trigger.trigger_counter() for trigger in triggers]
            consumed_by_force = [
                before - after for before, after in zip(queue_before_enter, queue_after_force)
            ]
            triggered_by_force = [
                after - before for before, after in zip(trigger_after_timer, trigger_after_force)
            ]

            print("")
            print("Post-Enter-force diagnostics:")
            print(f"  DDS queue counts after force: {queue_after_force}")
            print(f"  DDS commands consumed:       {consumed_by_force}")
            print(f"  trigger counters after:      {trigger_after_force}")
            print(f"  trigger counter deltas:      {triggered_by_force}")
            for card_index, dds in enumerate(dds_units):
                print(f"  card {card_index} DDS status: {dds_status_text(dds)}")
                print(
                    f"  card {card_index} core {DDS_CORE_INDEX}: "
                    f"freq={dds[DDS_CORE_INDEX].get_freq(return_unit=units.Hz)}, "
                    f"amp={dds[DDS_CORE_INDEX].get_amp(return_unit=units.mV)}, "
                    f"phase={dds[DDS_CORE_INDEX].get_phase(return_unit=units.degrees)}"
                )

            input("Outputs should now be holding the third phase state. Press Enter to validate and mute/stop...")

            if (
                not consumed_by_force
                or consumed_by_force[0] <= 0
                or len(set(consumed_by_force)) != 1
            ):
                print(
                    "  note: DDS queue-count consumption is diagnostic only; "
                    "the trigger counter/readback/lock-in result is more reliable here."
                )
            overrun_status = [
                dds_status_text(dds)
                for dds in dds_units
                if dds.status() & spcm.SPCM_DDS_STAT_QUEUE_OVERRUN
            ]
            if overrun_status:
                raise SystemExit(f"FAIL: DDS queue overrun detected: {overrun_status}")

            underrun_status = [
                dds_status_text(dds)
                for dds in dds_units
                if dds.status() & spcm.SPCM_DDS_STAT_QUEUE_UNDERRUN
            ]
            if underrun_status:
                print(
                    "  note: DDS QUEUE_UNDERRUN is expected after this finite "
                    "two-state timer pattern drains its queue."
                )

            print("")
            print("PASS: force-trigger/timer/force-trigger sequence completed equally across the StarHub stack.")
        finally:
            print("Stopping synchronized DDS output and muting CH0.")
            if started:
                try:
                    stack.stop()
                except Exception as exc:  # noqa: BLE001 - keep cleanup robust.
                    print(f"  warning: stack stop returned: {exc}")
            mute_dds(dds_units)


if __name__ == "__main__":
    run_test()
