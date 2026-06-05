"""
Concise reference for StarHub EXT0 trigger OR with DDS cards.

Cards listed in TRIGGER_SOURCE_INDICES contribute their physical EXT0 inputs to
the StarHub trigger OR. All cards in the enabled StarHub group receive the
resulting synchronized card-trigger event, including cards whose local trigger
mask is NONE.
"""

import spcm
from spcm import units


# Extend this list when the four-card stack is installed.
CARD_IDENTIFIERS = ["/dev/spcm0", "/dev/spcm1"]
# CARD_IDENTIFIERS = ["/dev/spcm0", "/dev/spcm1", "/dev/spcm2", "/dev/spcm3"]
SYNC_IDENTIFIER = "sync0"

# Future four-card example: {0, 2} enables two Trig In ports as OR sources.
TRIGGER_SOURCE_INDICES = {0, 1}
# TRIGGER_SOURCE_INDICES = {0, 2}


def configure_trigger(card: spcm.Card, is_source: bool) -> None:
    trigger = spcm.Trigger(card)
    trigger.or_mask(spcm.SPC_TMASK_EXT0 if is_source else spcm.SPC_TMASK_NONE)
    trigger.and_mask(spcm.SPC_TMASK_NONE)

    if is_source:
        trigger.ext0_mode(spcm.SPC_TM_POS)
        trigger.ext0_level0(0.5 * units.V)
        trigger.ext0_coupling(spcm.COUPLING_DC)
        trigger.termination(0)


def configure_dds(card: spcm.Card) -> spcm.DDS:
    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0)
    channels.enable(True)
    channels.output_load(50 * units.ohm)
    channels.amp(0.5 * units.V)
    card.write_setup()

    dds = spcm.DDS(card, channels=channels, check_features=True)
    dds.reset()
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)
    dds.phase_behaviour(spcm.SPCM_DDS_PHASE_JUMP)

    # Establish the running state immediately.
    dds[0].amp(100 * units.mV)
    dds[0].freq(300 * units.kHz)
    dds[0].phase(0 * units.degrees)
    dds.exec_now()
    dds.write_to_card()

    # Either enabled EXT0 input will execute this next update on every card.
    dds[0].phase(90 * units.degrees)
    dds.exec_at_trg()
    dds.write_to_card()
    return dds


with spcm.CardStack(card_identifiers=CARD_IDENTIFIERS, sync_identifier=SYNC_IDENTIFIER) as stack:
    for card_index, card in enumerate(stack.cards):
        card.card_mode(spcm.SPC_REP_STD_DDS)
        configure_trigger(card, is_source=card_index in TRIGGER_SOURCE_INDICES)
        configure_dds(card)

    # Enable all connected cards in the synchronized group and arm them together.
    stack.sync_enable(True)
    stack.start(spcm.M2CMD_CARD_ENABLETRIGGER)

    try:
        input("StarHub EXT0 OR is armed. Press Enter to stop...")
    finally:
        stack.stop()
