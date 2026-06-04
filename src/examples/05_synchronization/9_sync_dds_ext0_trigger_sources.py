"""
Debug physical EXT0 trigger distribution through StarHub, one source at a time.

Each source-card test uses a fresh StarHub run:
  selected card EXT0 -> StarHub -> both DDS engines
  other card trigger mask = NONE

The script asks the user to send one or more physical rising edges into the
selected card's Trig In / EXT0 port. Both trigger-engine counters should advance,
and both DDS queues should consume the same number of commands.
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


def print_counts(label: str, counts: list[int], counter_name: str) -> None:
    print(label)
    for card_index, count in enumerate(counts):
        print(f"  card {card_index} {counter_name}: {count}")


def dds_status_text(dds: spcm.DDS) -> str:
    status = dds.status()
    names = []
    if status & spcm.SPCM_DDS_STAT_WAITING_FOR_TRG:
        names.append("WAITING_FOR_TRG")
    if status & spcm.SPCM_DDS_STAT_QUEUE_UNDERRUN:
        names.append("QUEUE_UNDERRUN")
    if status & spcm.SPCM_DDS_STAT_QUEUE_OVERRUN:
        names.append("QUEUE_OVERRUN")
    return f"0x{status:x} ({', '.join(names) if names else 'none'})"


def print_dds_diagnostics(label: str, dds_units: list[spcm.DDS]) -> None:
    print(label)
    for card_index, dds in enumerate(dds_units):
        print(
            f"  card {card_index}: "
            f"trg_src={dds.get_trg_src()}, "
            f"queue_cmd_count={dds.queue_cmd_count()}, "
            f"status={dds_status_text(dds)}"
        )


def configure_card(
    card: spcm.Card,
    card_index: int,
    source_index: int,
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
    trigger.or_mask(spcm.SPC_TMASK_EXT0 if card_index == source_index else spcm.SPC_TMASK_NONE)
    trigger.and_mask(spcm.SPC_TMASK_NONE)
    trigger.ext0_mode(spcm.SPC_TM_POS)
    trigger.ext0_level0(args.trigger_level_v * units.V)
    trigger.ext0_coupling(spcm.COUPLING_DC)
    trigger.termination(1 if args.termination else 0)

    card.write_setup()

    dds = spcm.DDS(card, channels=channels, check_features=True)
    dds.reset()

    # DDS trigger source is a shadow setting. Latch it explicitly before
    # queueing updates that must wait for card/StarHub trigger events.
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
    if card_index == source_index:
        print("  trigger source: EXT0 positive edge")
        print(f"  EXT0 level: {args.trigger_level_v} V")
        print(f"  EXT0 termination: {'on' if args.termination else 'off'}")
    else:
        print("  trigger source: NONE")
    print(f"  armed DDS updates after initialization: {args.armed_triggers}")
    print(f"  DDS trigger source after initialization: {dds.get_trg_src()}")
    print(f"  DDS queue command count after initialization: {dds.queue_cmd_count()}")
    print(f"  DDS status after initialization: {dds_status_text(dds)}")
    return dds, trigger


def both_queues_consumed_equally(before: list[int], after: list[int]) -> bool:
    consumed = [old - new for old, new in zip(before, after)]
    return consumed[0] > 0 and len(set(consumed)) == 1


def run_source_test(source_index: int, args: argparse.Namespace) -> bool:
    print("")
    print("=" * 72)
    print(f"Testing EXT0 source card {source_index} ({CARD_IDENTIFIERS[source_index]})")
    print(f"Only card {source_index} will have EXT0 enabled; the other card uses trigger NONE.")

    with spcm.CardStack(card_identifiers=CARD_IDENTIFIERS, sync_identifier=SYNC_IDENTIFIER) as stack:
        print_sync_info(stack)

        dds_units = []
        triggers = []
        for card_index, card in enumerate(stack.cards):
            dds, trigger = configure_card(card, card_index, source_index, args)
            dds_units.append(dds)
            triggers.append(trigger)

        enable_mask = stack.sync_enable(True)
        print(f"StarHub enable mask: 0x{enable_mask:x}")

        try:
            stack.start(spcm.M2CMD_CARD_ENABLETRIGGER)
            time.sleep(args.settle_s)

            print_dds_diagnostics("DDS diagnostics after StarHub start:", dds_units)

            print("")
            print(f"Connect the trigger source to card {source_index} Trig In / EXT0 only.")
            print("Leave the other card's Trig In disconnected or quiet.")
            input("Press Enter after the cable is connected and the trigger source is idle...")
            time.sleep(args.settle_s)

            before_queue = queue_counts(dds_units)
            before_trigger = trigger_counts(triggers)
            print_counts("Before physical EXT0 pulses:", before_queue, "DDS queue command count")
            print_counts("Before physical EXT0 pulses:", before_trigger, "trigger-engine counter")
            print_dds_diagnostics("DDS diagnostics before physical EXT0 pulses:", dds_units)

            print("")
            print("Generate one or more rising edges now.")
            input("Press Enter after the trigger pulses have happened...")
            time.sleep(args.settle_s)

            after_queue = queue_counts(dds_units)
            after_trigger = trigger_counts(triggers)
            print_counts("After physical EXT0 pulses:", after_queue, "DDS queue command count")
            print_counts("After physical EXT0 pulses:", after_trigger, "trigger-engine counter")
            print_dds_diagnostics("DDS diagnostics after physical EXT0 pulses:", dds_units)

            ext_passed = both_queues_consumed_equally(before_queue, after_queue)
            trigger_seen = any(new > old for old, new in zip(before_trigger, after_trigger))

            print(f"Physical trigger engine saw pulse(s): {'YES' if trigger_seen else 'NO'}")
            print(f"Physical EXT0 consumed both DDS queues equally: {'PASS' if ext_passed else 'FAIL'}")
        finally:
            print("Stopping synchronized DDS output.")
            stack.stop()

    passed = trigger_seen and ext_passed
    print(f"Result for EXT0 source card {source_index}: {'PASS' if passed else 'FAIL'}")
    return passed


def main() -> None:
    parser = argparse.ArgumentParser(description="Debug one EXT0 StarHub source at a time.")
    parser.add_argument("--source", type=int, choices=range(len(CARD_IDENTIFIERS)))
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
        raise ValueError("--armed-triggers must be at least 2.")

    source_indices = [args.source] if args.source is not None else range(len(CARD_IDENTIFIERS))
    results = [run_source_test(source_index, args) for source_index in source_indices]

    if all(results):
        print("")
        print("PASS: every tested EXT0 source triggered both DDS engines through StarHub.")
    else:
        raise SystemExit("FAIL: at least one single-source EXT0 StarHub test failed.")


if __name__ == "__main__":
    main()
