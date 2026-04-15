"""
Spectrum Instrumentation GmbH (c) 2024

00_pg_trigger_dds_external_loopback.py

Generate phase-locked digital markers on X0 and X1 while using X1 as an
external trigger loopback into Ext0 to define the DDS start phase.

Intended wiring for a quick loopback test:
- connect X1 to the card's external trigger input Ext0

Want to test the phase alignment precisely. Using N1_TICKS = 2**9 and k=2**23. Frequency is around 244 kHz

Behavior:
- X0 and X1 output continuous pulses with an exact period of N1 clock ticks
- DDS channel 0 and channel 1 are prepared with the same locked sine frequency,
  0 deg phase, and 100 mV output level
- the first rising edge from X1 into Ext0 activates the DDS command step
- after that initial trigger, the digital marker and DDS remain phase-locked
  because both are commensurate on the same 125 MHz timing grid
"""

import spcm
from spcm import units


EXTERNAL_REFERENCE = 10 * units.MHz
CLOCK_TERMINATION_50OHM = False

FS_HZ = 125_000_000.0
TICK_S = 1.0 / FS_HZ
N1_TICKS = 2**9
PULSE_HIGH_TICKS = 2**8
DDS_GRID_STEP_HZ = FS_HZ / (2**9)
DDS_GRID_INDEX = round(300_000.0 / DDS_GRID_STEP_HZ)
LOCKED_DDS_FREQUENCY_HZ = DDS_GRID_INDEX * DDS_GRID_STEP_HZ

CHANNEL_RANGE = 500 * units.mV
DDS_OUTPUT_LEVEL = 100 * units.mV
TRIGGER_LEVEL = 0.5 * units.V
REFERENCE_CORE_INDEX = 0
TEST_CORE_INDEX = 8


def print_section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def initialize_dds_on_trigger(dds: spcm.DDS) -> None:
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_CARD)
    dds.phase_behaviour(spcm.SPCM_DDS_PHASE_JUMP)
    
    # Apply the trigger-source change
    dds.exec_now()

    dds[REFERENCE_CORE_INDEX].freq(LOCKED_DDS_FREQUENCY_HZ * units.Hz)
    dds[REFERENCE_CORE_INDEX].amp(DDS_OUTPUT_LEVEL)
    dds[REFERENCE_CORE_INDEX].phase(0 * units.degrees)

    dds[TEST_CORE_INDEX].freq(LOCKED_DDS_FREQUENCY_HZ * units.Hz)
    dds[TEST_CORE_INDEX].amp(DDS_OUTPUT_LEVEL)
    dds[TEST_CORE_INDEX].phase(0 * units.degrees)

    # Trigger from the XIO to get a known 0-degree start condition.
    dds.exec_at_trg()
    dds.write_to_card()


def configure_pulse_generators(card: spcm.Card) -> tuple[spcm.PulseGenerators, float]:
    multi_ios = spcm.MultiPurposeIOs(card)
    multi_ios[0].x_mode(spcm.SPCM_XMODE_PULSEGEN)
    multi_ios[1].x_mode(spcm.SPCM_XMODE_PULSEGEN)

    pulse_generators = spcm.PulseGenerators(
        card,
        enable=spcm.SPCM_PULSEGEN_ENABLE0 | spcm.SPCM_PULSEGEN_ENABLE1,
    )
    pulse_gen_clock = pulse_generators.get_clock()

    for index in (0, 1):
        pulse_generators[index].mode(spcm.SPCM_PULSEGEN_MODE_TRIGGERED)
        pulse_generators[index].period_length(N1_TICKS)
        pulse_generators[index].high_length(PULSE_HIGH_TICKS)
        pulse_generators[index].delay(0)
        pulse_generators[index].num_loops(0)
        pulse_generators[index].mux1(spcm.SPCM_PULSEGEN_MUX1_SRC_UNUSED)
        pulse_generators[index].mux2(spcm.SPCM_PULSEGEN_MUX2_SRC_SOFTWARE)

    pulse_generators.write_setup()
    return pulse_generators, pulse_gen_clock


def mute_dds(dds: spcm.DDS) -> None:
    dds[REFERENCE_CORE_INDEX].amp(0)
    dds[TEST_CORE_INDEX].amp(0)
    dds.exec_now()
    dds.write_to_card()


card: spcm.Card

# with spcm.Card('/dev/spcm0') as card:                         # if you want to open a specific card
# with spcm.Card('TCPIP::192.168.1.10::inst0::INSTR') as card:  # if you want to open a remote card
# with spcm.Card(serial_number=12345) as card:                  # if you want to open a card by its serial number
with spcm.Card(card_type=spcm.SPCM_TYPE_AO) as card:            # if you want to open the first card of a specific type

    if card.num_channels() < 2:
        raise spcm.SpcmException(
            text="This loopback test needs at least two analog output channels."
        )

    card.card_mode(spcm.SPC_REP_STD_DDS)

    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0 | spcm.CHANNEL1)
    channels[0].enable(True)
    channels[1].enable(True)
    channels[0].output_load(50 * units.ohm)
    channels[1].output_load(50 * units.ohm)
    channels[0].amp(CHANNEL_RANGE)
    channels[1].amp(CHANNEL_RANGE)

    clock = spcm.Clock(card)
    clock.mode(spcm.SPC_CM_EXTREFCLOCK)
    clock.reference_clock(EXTERNAL_REFERENCE)
    clock.termination(CLOCK_TERMINATION_50OHM)
    sample_rate = clock.sample_rate(clock.max_sample_rate(return_unit=units.Hz), return_unit=units.Hz)
    clock.clock_output(False)

    trigger = spcm.Trigger(card)
    trigger.or_mask(spcm.SPC_TMASK_EXT0)
    trigger.ext0_mode(spcm.SPC_TM_POS)
    trigger.ext0_level0(TRIGGER_LEVEL)
    trigger.ext0_coupling(spcm.COUPLING_DC)

    card.write_setup()

    pulse_generators, pulse_gen_clock = configure_pulse_generators(card)

    dds = spcm.DDS(card, channels=channels)
    dds.reset()
    initialize_dds_on_trigger(dds)

    marker_period_s = N1_TICKS * TICK_S
    marker_frequency_hz = 1.0 / marker_period_s

    print_section("Pulse Generator To DDS External Trigger Loopback")
    print(f"Card: {card.product_name()}")
    print(f"External reference: {EXTERNAL_REFERENCE}")
    print(f"Clock mode: external reference")
    print(f"Clock input termination: {'50 ohm' if clock.termination() else '5 kohm'}")
    print(f"Actual sample rate: {sample_rate}")
    print(f"Pulse-generator clock: {pulse_gen_clock} Hz")
    print(f"Pulse outputs: X0 and X1")
    print(f"Pulse period ticks: {N1_TICKS}")
    print(f"Pulse HIGH ticks: {PULSE_HIGH_TICKS}")
    print(f"Marker period: {marker_period_s:.12g} s")
    print(f"Marker frequency: {marker_frequency_hz:.12g} Hz")
    print(f"DDS channel 0 core: {REFERENCE_CORE_INDEX}")
    print(f"DDS channel 1 core: {TEST_CORE_INDEX}")
    print(f"DDS output frequency used: {LOCKED_DDS_FREQUENCY_HZ:.12g} Hz")
    print(f"DDS output level: {DDS_OUTPUT_LEVEL}")
    print(f"DDS trigger source: card trigger via Ext0")
    print(f"Trigger mode: positive edge on Ext0")
    print(f"Trigger level: {TRIGGER_LEVEL}")
    print()
    print("Connect X1 to the card trigger input Ext0 before starting.")
    print("The card trigger engine is armed first.")
    print("X0 and X1 begin pulsing only after the pulse generators are force-started.")
    print("The first X1 edge into Ext0 defines the DDS trigger event.")

    card.start(spcm.M2CMD_CARD_ENABLETRIGGER)
    pulse_generators.force()

    try:
        input("Press Enter to stop the pulse generators and mute DDS outputs.")
    finally:
        mute_dds(dds)
        card.stop()
        pulse_generators.enable(False)
        pulse_generators.write_setup()
        channels[0].enable(False)
        channels[1].enable(False)
        card.write_setup()
        print("Pulse generators stopped, DDS outputs muted, and analog channels disabled.")
