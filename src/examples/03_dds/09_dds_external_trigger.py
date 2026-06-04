"""  
Spectrum Instrumentation GmbH (c) 2024

9_dds_external_trigger.py

External Trigger - wait for trigger than turn-on carrier 0 and afterwards turn it off again

Example for analog replay cards (AWG) for the the M4i and M4x card-families with installed DDS option.

See the README file in the parent folder of this examples directory for information about how to use this example.

See the LICENSE file for the conditions under which this software may be used and distributed.
"""

import spcm
from spcm import units

import time


card : spcm.Card
# with spcm.Card('/dev/spcm0') as card:                         # if you want to open a specific card
# with spcm.Card('TCPIP::192.168.1.10::inst0::INSTR') as card:  # if you want to open a remote card
# with spcm.Card(serial_number=12345) as card:                  # if you want to open a card by its serial number
with spcm.Card('/dev/spcm1') as card:            # if you want to open the first card of a specific type

    # setup card for DDS
    card.card_mode(spcm.SPC_REP_STD_DDS)

    # Setup the card
    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0)
    channels.enable(True)
    channels.amp(500 * units.mV)
    channels.output_load(50 * units.ohm)
    
    # Activate external trigger mode
    trigger = spcm.Trigger(card)
    trigger.or_mask(spcm.SPC_TMASK_EXT0)
    trigger.ext0_mode(spcm.SPC_TM_POS) # positive edge
    trigger.ext0_level0(0.5 * units.V) # Trigger level is 0.5 V (500 mV)
    trigger.ext0_coupling(spcm.COUPLING_DC) # set DC coupling
    trigger.termination(0) # high impedance input; use 1 for 50 ohm termination
    card.write_setup() # IMPORTANT! this turns on the card's system clock signals, that are required for DDS to work
    
    # Setup DDS
    dds = spcm.DDS(card, channels=channels)
    core0 = dds[0]
    dds.reset()

    # Start the DDS test
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)

    # Create one carrier
    core0.amp(40 * units.percent)
    core0.freq(5 * units.MHz)
    dds.exec_at_trg()

    # each trigger event will change the generated frequency by 1 MHz
    for i in range(1, 11):
        core0.freq(5 * units.MHz + i * units.MHz)
        dds.exec_at_trg()
    dds.write_to_card()

    # Start command including enable of trigger engine. No software force trigger:
    # each external TTL rising edge on EXT0 advances the DDS command queue.
    card.start(spcm.M2CMD_CARD_ENABLETRIGGER)

    print("Waiting for rising TTL edges on EXT0 / Trig In.")
    print("Press Ctrl+C to stop.")

    last_trigger_count = trigger.trigger_counter()
    last_dds_count = dds.trg_count()
    print(f"Initial trigger counter: {last_trigger_count}, DDS trigger count: {last_dds_count}")

    try:
        while True:
            trigger_count = trigger.trigger_counter()
            dds_count = dds.trg_count()
            if trigger_count != last_trigger_count or dds_count != last_dds_count:
                print(f"TTL count: {trigger_count}, DDS trigger count: {dds_count}")
                last_trigger_count = trigger_count
                last_dds_count = dds_count
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("Stopping...")
    finally:
        card.stop()

