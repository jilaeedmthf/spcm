"""
StarHub DDS synchronization smoke test for two AWG cards.

This is a DDS-mode counterpart to 2_sync_gen_single.py. It opens /dev/spcm0 and
/dev/spcm1 through sync0, arms one DDS carrier on channel 0 of each card, starts
both cards through the StarHub handle, and force-triggers the synchronized stack.
Use a scope on CH0 of both cards to verify that the relative phase is fixed.
"""

import argparse
import time

import spcm
from spcm import units


CARD_IDENTIFIERS = ["/dev/spcm0", "/dev/spcm1"]
SYNC_IDENTIFIER = "sync0"


def configure_trigger(card: spcm.Card, use_software_trigger: bool) -> None:
    trigger = spcm.Trigger(card)
    trigger.or_mask(spcm.SPC_TMASK_SOFTWARE if use_software_trigger else spcm.SPC_TMASK_NONE)
    trigger.and_mask(spcm.SPC_TMASK_NONE)


def print_sync_info(stack: spcm.CardStack) -> None:
    if not stack.sync:
        print("No StarHub sync handle opened.")
        return

    num_connectors = stack.sync.num_connectors()
    sync_count = stack.sync.sync_count()
    print(f"StarHub connectors: {num_connectors}")
    print(f"StarHub synced cards: {sync_count}")
    for index in range(sync_count):
        card_index = stack.sync.card_index(index)
        cable = stack.sync.cable_connection(index)
        print(f"  sync index {index}: card index {card_index}, cable connector {cable}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a two-card StarHub DDS sync smoke test.")
    parser.add_argument("--duration-s", type=float, default=5.0, help="Output duration before stopping.")
    parser.add_argument("--freq-hz", type=float, default=300_000.0, help="DDS frequency for both cards.")
    parser.add_argument("--amp-mv", type=float, default=100.0, help="DDS carrier amplitude per card.")
    parser.add_argument("--card-amp-v", type=float, default=0.5, help="Analog output range per channel.")
    parser.add_argument("--phase1-deg", type=float, default=0.0, help="Phase for /dev/spcm0 core 0.")
    parser.add_argument("--phase2-deg", type=float, default=0.0, help="Phase for /dev/spcm1 core 0.")
    args = parser.parse_args()

    with spcm.CardStack(
        card_identifiers=CARD_IDENTIFIERS,
        sync_identifier=SYNC_IDENTIFIER,
        find_sync=True,
    ) as stack:
        print_sync_info(stack)

        starhub_master_index = stack.sync_id
        print(f"Using card {starhub_master_index} as software trigger source for the sync group.")

        for index, card in enumerate(stack.cards):
            if card.function_type() != spcm.SPCM_TYPE_AO:
                raise spcm.SpcmException(
                    f"This is an example for D/A cards.\n{card} is not supported by this example."
                )

            print(f"Found card {index}: {card}")
            print(f"  features: 0x{card.features():x}, ext_features: 0x{card.ext_features():x}")

            card.card_mode(spcm.SPC_REP_STD_DDS)

            channels = spcm.Channels(card, card_enable=spcm.CHANNEL0)
            channels.enable(True)
            channels.output_load(50 * units.ohm)
            channels.amp(args.card_amp_v * units.V)

            configure_trigger(card, use_software_trigger=(index == starhub_master_index))

            card.write_setup()

            dds = spcm.DDS(card, channels=channels, check_features=True)
            dds.reset()
            dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)
            dds.phase_behaviour(spcm.SPCM_DDS_PHASE_JUMP)

            phase = args.phase1_deg if index == 0 else args.phase2_deg
            dds[0].amp(args.amp_mv * units.mV)
            dds[0].freq(args.freq_hz * units.Hz)
            dds[0].phase(phase * units.degrees)
            dds.exec_at_trg()
            dds.write_to_card()

            print(
                f"  DDS core 0: freq={dds[0].get_freq(return_unit=units.Hz)}, "
                f"amp={dds[0].get_amp(return_unit=units.mV)}, "
                f"phase={dds[0].get_phase(return_unit=units.degrees)}"
            )
        enable_mask = stack.sync_enable(True)
        print(f"StarHub enable mask: 0x{enable_mask:x}")

        stack.start(spcm.M2CMD_CARD_ENABLETRIGGER)
        stack.force_trigger()
        print("Synchronized DDS output is running.")

        time.sleep(max(args.duration_s, 0.0))

        print("Stopping synchronized DDS output.")
        stack.stop()


if __name__ == "__main__":
    main()
