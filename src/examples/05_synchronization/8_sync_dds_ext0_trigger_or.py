"""
Interactive StarHub OR test using the physical Trig In / EXT0 ports.

Both cards are configured as physical trigger sources at the same time:
  /dev/spcm0 EXT0 OR /dev/spcm1 EXT0 -> StarHub -> both DDS engines

The script starts the synchronized stack once, then guides the user through
testing one physical Trig In at a time. For each step, connect the trigger source
only to the requested card, generate one or more rising edges, and press Enter.
Both trigger-engine counters should increment and both DDS queues should consume
the same number of commands.
"""

import argparse
import time

import spcm
from spcm import units


CARD_IDENTIFIERS = ["/dev/spcm0", "/dev/spcm1"]
SYNC_IDENTIFIER = "sync0"


def print_sync_info(stack: spcm.CardStack) -> None:
    print(f"StarHub connectors: {stack.sync.num_connectors()}")
    print(f"StarHub synced cards: {stack.sync.sync_count()}")
    for index in range(stack.sync.sync_count()):
        print(
            f"  sync index {index}: "
            f"card index {stack.sync.card_index(index)}, "
            f"cable connector {stack.sync.cable_connection(index)}"
        )


def queue_counts(dds_units: list[spcm.DDS]) -> list[int]:
    return [dds.queue_cmd_count() for dds in dds_units]


def trigger_counts(triggers: list[spcm.Trigger]) -> list[int]:
    return [trigger.trigger_counter() for trigger in triggers]


def print_trigger_counters(label: str, counts: list[int]) -> None:
    print(label)
    for card_index, count in enumerate(counts):
        print(f"  card {card_index} trigger-engine counter: {count}")


def print_queue_counts(label: str, counts: list[int]) -> None:
    print(label)
    for card_index, count in enumerate(counts):
        print(f"  card {card_index} DDS queue command count: {count}")


def both_advanced_equally(before: list[int], after: list[int]) -> bool:
    deltas = [new - old for old, new in zip(before, after)]
    return deltas[0] > 0 and len(set(deltas)) == 1


def both_queues_consumed_equally(before: list[int], after: list[int]) -> bool:
    consumed = [old - new for old, new in zip(before, after)]
    return consumed[0] > 0 and len(set(consumed)) == 1


def configure_card(
    card: spcm.Card,
    card_index: int,
    args: argparse.Namespace,
) -> tuple[spcm.DDS, spcm.Trigger]:
    if card.function_type() != spcm.SPCM_TYPE_AO:
        raise spcm.SpcmException(f"{card} is not an analog output card.")

    print(f"Found card {card_index}: {card}")
    print(f"  features: 0x{card.features():x}, ext_features: 0x{card.ext_features():x}")

    card.card_mode(spcm.SPC_REP_STD_DDS)

    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0)
    channels.enable(True)
    channels.output_load(50 * units.ohm)
    channels.amp(args.card_amp_v * units.V)

    trigger = spcm.Trigger(card)
    trigger.or_mask(spcm.SPC_TMASK_EXT0)
    trigger.and_mask(spcm.SPC_TMASK_NONE)
    trigger.ext0_mode(spcm.SPC_TM_POS)
    trigger.ext0_level0(args.trigger_level_v * units.V)
    trigger.ext0_coupling(spcm.COUPLING_DC)
    trigger.termination(1 if args.termination else 0)

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

    for trigger_index in range(args.armed_triggers):
        phase_deg = ((trigger_index + 1) * args.phase_step_deg) % 360
        dds[0].phase(phase_deg * units.degrees)
        dds.exec_at_trg()
    dds.write_to_card()

    print(f"  trigger OR mask: 0x{trigger.or_mask():x}")
    print(f"  EXT0 mode: positive edge")
    print(f"  EXT0 level: {args.trigger_level_v} V")
    print(f"  EXT0 termination: {'on' if args.termination else 'off'}")
    print(f"  armed DDS trigger updates after initialization: {args.armed_triggers}")
    print(f"  DDS queue command count before start: {dds.queue_cmd_count()}")
    return dds, trigger


def test_one_input(
    source_index: int,
    dds_units: list[spcm.DDS],
    triggers: list[spcm.Trigger],
    args: argparse.Namespace,
) -> bool:
    print("")
    print("=" * 72)
    print(f"Test physical Trig In on card {source_index} ({CARD_IDENTIFIERS[source_index]})")
    print("Connect the trigger source to this card's Trig In / EXT0 only.")
    print("Leave the other card's Trig In disconnected or quiet.")
    input("Press Enter after the cable is connected and the trigger source is idle...")
    time.sleep(args.settle_s)

    before_queue = queue_counts(dds_units)
    before_triggers = trigger_counts(triggers)
    print_queue_counts("DDS queues before the test pulse:", before_queue)
    print_trigger_counters("Trigger-engine counters before the test pulse:", before_triggers)

    print("")
    print("Generate one or more rising edges now.")
    input("Press Enter after the trigger edge(s) have happened...")
    time.sleep(args.settle_s)

    after_queue = queue_counts(dds_units)
    after_triggers = trigger_counts(triggers)
    print_queue_counts("DDS queues after the test pulse:", after_queue)
    print_trigger_counters("Trigger-engine counters after the test pulse:", after_triggers)

    trigger_passed = both_advanced_equally(before_triggers, after_triggers)
    queue_passed = both_queues_consumed_equally(before_queue, after_queue)
    passed = trigger_passed and queue_passed
    print(f"Result for card {source_index} Trig In: {'PASS' if passed else 'FAIL'}")
    if not passed:
        print(f"  trigger counters advanced equally: {'YES' if trigger_passed else 'NO'}")
        print(f"  DDS queues consumed equally: {'YES' if queue_passed else 'NO'}")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive StarHub EXT0 OR test.")
    parser.add_argument("--freq-hz", type=float, default=300_000.0)
    parser.add_argument("--amp-mv", type=float, default=100.0)
    parser.add_argument("--card-amp-v", type=float, default=0.5)
    parser.add_argument("--trigger-level-v", type=float, default=0.5)
    parser.add_argument("--termination", action="store_true")
    parser.add_argument("--armed-triggers", type=int, default=32)
    parser.add_argument("--phase-step-deg", type=float, default=45.0)
    parser.add_argument("--settle-s", type=float, default=0.25)
    args = parser.parse_args()

    if args.armed_triggers < 2:
        raise ValueError("--armed-triggers should be at least 2 for this two-input test.")

    with spcm.CardStack(card_identifiers=CARD_IDENTIFIERS, sync_identifier=SYNC_IDENTIFIER) as stack:
        print_sync_info(stack)

        dds_units = []
        triggers = []
        for card_index, card in enumerate(stack.cards):
            dds, trigger = configure_card(card, card_index, args)
            dds_units.append(dds)
            triggers.append(trigger)

        enable_mask = stack.sync_enable(True)
        print(f"StarHub enable mask: 0x{enable_mask:x}")
        print("")
        print("Starting the StarHub-synchronized DDS group.")
        print("No software trigger will be forced by this script.")

        results = []
        try:
            stack.start(spcm.M2CMD_CARD_ENABLETRIGGER)
            time.sleep(args.settle_s)
            print_queue_counts("DDS queues immediately after start:", queue_counts(dds_units))

            for source_index in range(len(CARD_IDENTIFIERS)):
                results.append(test_one_input(source_index, dds_units, triggers, args))
        finally:
            print("")
            print("Stopping synchronized DDS output.")
            stack.stop()

    if all(results):
        print("")
        print("PASS: both physical Trig In ports triggered the StarHub group.")
    else:
        raise SystemExit("FAIL: at least one physical Trig In test did not consume both DDS queues equally.")


if __name__ == "__main__":
    main()
