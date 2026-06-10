"""Generate two static DDS tones on /dev/spcm0 CH0 using a 10 MHz reference.

Wiring:
  10 MHz reference -> /dev/spcm0 Clk In
  /dev/spcm0 CH0   -> measurement input

This is a focused lock-in/lab-bench helper based on
02_dds_multiple_static_carriers.py. It uses two DDS cores on channel 0, locks
the card clock to an external 10 MHz reference, and mutes the DDS output before
exit.
"""

import spcm
from spcm import units


CARD_IDENTIFIER = "/dev/spcm0"
REFERENCE_CLOCK = 10 * units.MHz
CLOCK_TERMINATION_50OHM = True
CLOCK_THRESHOLD = 0 * units.mV

CHANNEL_RANGE = 1.0 * units.V
OUTPUT_LOAD = units.highZ

DDS_CORE_A = 0
DDS_CORE_B = 1
DDS_FREQ_A = 301 * units.kHz
DDS_FREQ_B = 100 * units.kHz
DDS_AMPLITUDE = 500 * units.mV


def configure_external_reference(card: spcm.Card) -> spcm.Clock:
    """Configure the card PLL to lock to the external 10 MHz reference."""
    clock = spcm.Clock(card)
    clock.mode(spcm.SPC_CM_EXTREFCLOCK)
    clock.reference_clock(REFERENCE_CLOCK)
    clock.termination(CLOCK_TERMINATION_50OHM)
    clock.threshold(CLOCK_THRESHOLD)
    sample_rate = clock.sample_rate(clock.max_sample_rate(return_unit=units.Hz), return_unit=units.Hz)
    clock.clock_output(False)

    print("External reference configuration:")
    print(f"  reference clock:   {REFERENCE_CLOCK}")
    print(f"  sample rate:       {sample_rate}")
    print(f"  clock termination: {'50 ohm' if clock.termination() else 'high impedance'}")
    print(f"  clock threshold:   {clock.threshold(return_unit=units.mV)}")
    print("  clock output:      disabled")
    return clock


def configure_dds(card: spcm.Card) -> tuple[spcm.Channels, spcm.DDS]:
    """Configure CH0 with two static DDS carriers."""
    card.card_mode(spcm.SPC_REP_STD_DDS)

    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0)
    channels[0].enable(True)
    channels[0].output_load(OUTPUT_LOAD)
    channels[0].amp(CHANNEL_RANGE)

    configure_external_reference(card)
    card.write_setup()

    pll_locked = card.get_i(spcm.SPC_PLL_ISLOCKED)
    print(f"  PLL locked:        {pll_locked}")
    if pll_locked != 1:
        raise SystemExit("FAIL: /dev/spcm0 PLL did not lock to the external 10 MHz reference.")

    dds = spcm.DDS(card, channels=channels)
    dds.reset()
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)

    dds[DDS_CORE_A].amp(DDS_AMPLITUDE)
    dds[DDS_CORE_A].freq(DDS_FREQ_A)
    dds[DDS_CORE_A].phase(0 * units.degrees)

    dds[DDS_CORE_B].amp(DDS_AMPLITUDE)
    dds[DDS_CORE_B].freq(DDS_FREQ_B)
    dds[DDS_CORE_B].phase(0 * units.degrees)

    dds.exec_at_trg()
    dds.write_to_card()

    print("")
    print("DDS output configuration:")
    print(f"  card:              {CARD_IDENTIFIER}")
    print("  channel:           CH0")
    print(f"  output load:       high impedance")
    print(f"  channel range:     {CHANNEL_RANGE}")
    print(
        f"  core {DDS_CORE_A}:           "
        f"{dds[DDS_CORE_A].get_freq(return_unit=units.Hz)}, "
        f"{dds[DDS_CORE_A].get_amp(return_unit=units.mV)}"
    )
    print(
        f"  core {DDS_CORE_B}:           "
        f"{dds[DDS_CORE_B].get_freq(return_unit=units.Hz)}, "
        f"{dds[DDS_CORE_B].get_amp(return_unit=units.mV)}"
    )
    return channels, dds


def mute_outputs(card: spcm.Card, channels: spcm.Channels, dds: spcm.DDS) -> None:
    """Mute the two DDS cores and disable CH0."""
    dds[DDS_CORE_A].amp(0 * units.mV)
    dds[DDS_CORE_B].amp(0 * units.mV)
    dds.exec_now()
    dds.write_to_card()
    card.stop()
    channels[0].enable(False)
    card.write_setup()


card: spcm.Card
with spcm.Card(CARD_IDENTIFIER) as card:
    channels, dds = configure_dds(card)

    print("")
    print("Starting two-tone DDS output.")
    card.start(spcm.M2CMD_CARD_ENABLETRIGGER, spcm.M2CMD_CARD_FORCETRIGGER)

    try:
        input("Press Enter to mute CH0 and stop...")
    finally:
        mute_outputs(card, channels, dds)
        print("DDS output muted, card stopped, and CH0 disabled.")
