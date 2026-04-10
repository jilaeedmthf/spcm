"""
Spectrum Instrumentation GmbH (c) 2024

00_dds_phase_lockin_test.py

Lock-in oriented DDS phase test for a two-channel AWG setup.

This script generates two 300 kHz sine waves:
- channel 0: reference output with fixed phase
- channel 1: test output whose phase is stepped interactively

It is intended for checking the DDS output phase setting with an external
phase-sensitive instrument such as a lock-in amplifier.

The script prints both the requested phase and the API readback so that
documentation/API inconsistencies are visible while you measure the analog
output phase directly.
"""

import spcm
from spcm import units


FREQUENCY = 300 * units.kHz
EXTERNAL_REFERENCE = 10 * units.MHz
CLOCK_TERMINATION_50OHM = False
CHANNEL_RANGE = 500 * units.mV
OUTPUT_LEVEL = 100 * units.mV
REFERENCE_CORE_INDEX = 0
TEST_CORE_INDEX = 8


def print_section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def configure_two_channel_dds(card: spcm.Card) -> tuple[spcm.Channels, spcm.DDS, spcm.Clock, float]:
    if card.num_channels() < 2:
        raise spcm.SpcmException(
            text="This phase-lockin example needs at least two analog output channels."
        )

    card.card_mode(spcm.SPC_REP_STD_DDS)

    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0 | spcm.CHANNEL1)
    channels[0].enable(True)
    channels[1].enable(True)
    channels[0].output_load(50 * units.ohm)
    channels[1].output_load(50 * units.ohm)
    channels[0].amp(CHANNEL_RANGE)
    channels[1].amp(CHANNEL_RANGE)

    # Setup the card clock from an external 10 MHz reference to synchronize
    # the AWG with external lab equipment such as a lock-in amplifier.
    clock = spcm.Clock(card)
    clock.mode(spcm.SPC_CM_EXTREFCLOCK)
    clock.reference_clock(EXTERNAL_REFERENCE)
    clock.termination(CLOCK_TERMINATION_50OHM)
    sample_rate = clock.sample_rate(clock.max_sample_rate(return_unit=units.Hz), return_unit=units.Hz)
    clock.clock_output(False)
    card.write_setup()

    dds = spcm.DDS(card, channels=channels)
    dds.reset()
    dds.phase_behaviour(spcm.SPCM_DDS_PHASE_JUMP)
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_NONE)

    return channels, dds, clock, sample_rate


def initialize_pair(dds: spcm.DDS, test_phase_deg: float = 0.0) -> tuple[float, float]:
    dds[REFERENCE_CORE_INDEX].freq(FREQUENCY)
    dds[REFERENCE_CORE_INDEX].amp(OUTPUT_LEVEL)
    dds[REFERENCE_CORE_INDEX].phase(0 * units.degrees)

    dds[TEST_CORE_INDEX].freq(FREQUENCY)
    dds[TEST_CORE_INDEX].amp(OUTPUT_LEVEL)
    dds[TEST_CORE_INDEX].phase(test_phase_deg * units.degrees)

    dds.exec_now()
    dds.write_to_card()

    return (
        dds[REFERENCE_CORE_INDEX].get_phase(return_unit=units.degrees).magnitude,
        dds[TEST_CORE_INDEX].get_phase(return_unit=units.degrees).magnitude,
    )


def apply_pair(dds: spcm.DDS, test_phase_deg: float) -> tuple[float, float]:
    dds[REFERENCE_CORE_INDEX].freq(FREQUENCY)
    dds[REFERENCE_CORE_INDEX].amp(OUTPUT_LEVEL)
    dds[REFERENCE_CORE_INDEX].phase(0 * units.degrees)

    dds[TEST_CORE_INDEX].freq(FREQUENCY)
    dds[TEST_CORE_INDEX].amp(OUTPUT_LEVEL)
    dds[TEST_CORE_INDEX].phase(test_phase_deg * units.degrees)

    dds.exec_now()
    dds.write_to_card()

    return (
        dds[REFERENCE_CORE_INDEX].get_phase(return_unit=units.degrees).magnitude,
        dds[TEST_CORE_INDEX].get_phase(return_unit=units.degrees).magnitude,
    )


def mute_outputs(dds: spcm.DDS) -> None:
    dds[REFERENCE_CORE_INDEX].amp(0)
    dds[TEST_CORE_INDEX].amp(0)
    dds.exec_now()
    dds.write_to_card()


card: spcm.Card

# with spcm.Card('/dev/spcm0') as card:                         # if you want to open a specific card
# with spcm.Card('TCPIP::192.168.1.10::inst0::INSTR') as card:  # if you want to open a remote card
# with spcm.Card(serial_number=12345) as card:                  # if you want to open a card by its serial number
with spcm.Card(card_type=spcm.SPCM_TYPE_AO) as card:            # if you want to open the first card of a specific type

    channels, dds, clock, sample_rate = configure_two_channel_dds(card)

    expected_phase_step = 360.0 / (2**12)
    reported_phase_step = dds.avail_phase_step()
    phase_sequence_deg = [
        0.0,
        expected_phase_step / 4,
        expected_phase_step / 2,
        expected_phase_step,
        reported_phase_step / 2,
        reported_phase_step,
        45.0,
        45.0 + expected_phase_step / 4,
        45.0 + expected_phase_step / 2,
        45.0 + expected_phase_step,
    ]

    print_section("DDS Phase Lock-In Test")
    print(f"Card: {card.product_name()}")
    print(f"Active channels: {len(channels)}")
    print(f"Reference output: channel 0 at {FREQUENCY}")
    print(f"Test output:      channel 1 at {FREQUENCY}")
    print(f"External reference: {EXTERNAL_REFERENCE}")
    print(f"Clock mode:         external reference")
    print(f"Actual sample rate: {sample_rate}")
    print(f"Clock input termination: {'50 ohm' if clock.termination() else '5 kohm'}")
    print(f"Channel range:    {CHANNEL_RANGE}")
    print(f"Output level:     {OUTPUT_LEVEL}")
    print(f"Reference core:   {REFERENCE_CORE_INDEX}")
    print(f"Test core:        {TEST_CORE_INDEX}")
    print(f"Clock output:     {bool(clock.clock_output())}")
    print(f"Reported phase step: {reported_phase_step} deg")
    print(f"12-bit phase step:   {expected_phase_step} deg")
    print(f"Channel 0 core mask: {dds.get_cores_on_channel(0)}")
    print(f"Channel 1 core mask: {dds.get_cores_on_channel(1)}")

    ref_phase, test_phase = initialize_pair(dds, 0.0)
    print()
    print(
        f"Initial state applied. Reference readback: {ref_phase} deg, "
        f"test readback: {test_phase} deg"
    )

    card.start(spcm.M2CMD_CARD_ENABLETRIGGER, spcm.M2CMD_CARD_FORCETRIGGER)

    print()
    print("Connect channel 0 to the lock-in reference and channel 1 to the test input.")
    print("Press Enter to step through the requested test phases, or type q then Enter to stop.")

    try:
        for index, phase_deg in enumerate(phase_sequence_deg, start=1):
            user_input = input(f"\nStep {index}/{len(phase_sequence_deg)} ready? ")
            if user_input.strip().lower() in {"q", "quit", "exit"}:
                break

            ref_phase, test_phase = apply_pair(dds, phase_deg)
            print(
                f"Requested test phase: {phase_deg:.12g} deg | "
                f"reference readback: {ref_phase:.12g} deg | "
                f"test readback: {test_phase:.12g} deg | "
                f"delta: {test_phase - ref_phase:.12g} deg"
            )

        print()
        print("Phase stepping complete.")
        input("Press Enter when you are done with the final measurement.")
    finally:
        mute_outputs(dds)
        card.stop()
        channels[0].enable(False)
        channels[1].enable(False)
        card.write_setup()
        print("Outputs muted and analog channels disabled.")
