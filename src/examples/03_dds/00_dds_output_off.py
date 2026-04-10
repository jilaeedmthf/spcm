"""
Spectrum Instrumentation GmbH (c) 2024

00_dds_output_off.py

Small helper script that turns DDS output off by:
- muting all DDS cores
- writing the muted DDS state to the card
- stopping the card
- disabling all analog output channels

This is useful as a quick cleanup script while experimenting with DDS examples.

See the README file in the parent folder of this examples directory for
information about how to use this example.

See the LICENSE file for the conditions under which this software may be used
and distributed.
"""

import spcm


def mute_all_cores(dds: spcm.DDS) -> None:
    for core in dds:
        core.amp(0)


card: spcm.Card

# with spcm.Card('/dev/spcm0') as card:                         # if you want to open a specific card
# with spcm.Card('TCPIP::192.168.1.10::inst0::INSTR') as card:  # if you want to open a remote card
# with spcm.Card(serial_number=12345) as card:                  # if you want to open a card by its serial number
with spcm.Card(card_type=spcm.SPCM_TYPE_AO) as card:            # if you want to open the first card of a specific type

    card.card_mode(spcm.SPC_REP_STD_DDS)

    channels = spcm.Channels(card)
    channels.enable(True)

    dds = spcm.DDS(card, channels=channels)
    mute_all_cores(dds)
    dds.exec_now()
    dds.write_to_card()

    card.stop()
    channels.enable(False)
    card.write_setup()

    print("DDS cores muted, card stopped, and analog output channels disabled.")
