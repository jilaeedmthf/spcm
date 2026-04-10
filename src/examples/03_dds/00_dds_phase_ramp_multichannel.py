"""
Spectrum Instrumentation GmbH (c) 2024

00_dds_phase_ramp_multichannel.py

Demonstrate simultaneous phase ramping on 8 channels by applying one timed DDS
frequency-offset block and one timed return-to-baseline block.

The script toggles between two phase states:
- State A: [0, 45, 90, 135, 180, 225, 270, 315]
- State B: [0, -45, -90, -135, -180, -225, -270, -315]

The phase differences are wrapped to the shortest path in [-180, 180), while
the original phase lists are kept unchanged for simplicity.
"""

import spcm
from spcm import units


BASE_FREQUENCY = 300 * units.kHz
EXTERNAL_REFERENCE = 10 * units.MHz
CLOCK_TERMINATION_50OHM = False
CHANNEL_RANGE = 500 * units.mV
OUTPUT_LEVEL = 100 * units.mV

CHANNEL_INDICES = list(range(8))
CORE_INDICES = [0, 2, 4, 6, 8, 10, 12, 14]

STATE_A_PHASES_DEG = [0, 45, 90, 135, 180, 225, 270, 315]
STATE_B_PHASES_DEG = [0, -45, -90, -135, -180, -225, -270, -315]

DDS_STEP_HZ = 125e6 / (2**32)
PHASE_QUANTUM_DEG = 360.0 / (2**14)
DWELL_S = PHASE_QUANTUM_DEG / 360.0 / DDS_STEP_HZ


def print_section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def phase_delta_deg(current_deg: float, target_deg: float) -> float:
    return ((target_deg - current_deg + 180.0) % 360.0) - 180.0


def initialize_state(dds: spcm.DDS, phase_list_deg: list[float]) -> None:
    for core_index, phase_deg in zip(CORE_INDICES, phase_list_deg):
        dds[core_index].freq(BASE_FREQUENCY)
        dds[core_index].amp(OUTPUT_LEVEL)
        dds[core_index].phase(phase_deg * units.degrees)

    dds.exec_now()
    dds.write_to_card()


def queue_phase_step(
    dds: spcm.DDS,
    current_phase_list_deg: list[float],
    target_phase_list_deg: list[float],
    dwell_s: float,
) -> list[float]:
    delta_phases_deg = [
        phase_delta_deg(current_deg, target_deg)
        for current_deg, target_deg in zip(current_phase_list_deg, target_phase_list_deg)
    ]
    delta_freqs_hz = [
        delta_phase_deg / 360.0 / dwell_s
        for delta_phase_deg in delta_phases_deg
    ]

    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_TIMER)
    dds.trg_timer(dwell_s)
    for core_index, delta_freq_hz in zip(CORE_INDICES, delta_freqs_hz):
        dds[core_index].freq((BASE_FREQUENCY.to(units.Hz).magnitude + delta_freq_hz) * units.Hz)
    # Match the proven single-channel pattern: EXEC_NOW applies the offset
    # state immediately and starts the DDS timer for the scheduled return.
    dds.exec_now()

    for core_index in CORE_INDICES:
        dds[core_index].freq(BASE_FREQUENCY)
    dds.exec_at_trg()

    dds.write_to_card()
    return delta_freqs_hz


def mute_outputs(dds: spcm.DDS) -> None:
    for core_index in CORE_INDICES:
        dds[core_index].amp(0)
    dds.exec_now()
    dds.write_to_card()


card: spcm.Card

# with spcm.Card('/dev/spcm0') as card:                         # if you want to open a specific card
# with spcm.Card('TCPIP::192.168.1.10::inst0::INSTR') as card:  # if you want to open a remote card
# with spcm.Card(serial_number=12345) as card:                  # if you want to open a card by its serial number
with spcm.Card(card_type=spcm.SPCM_TYPE_AO) as card:            # if you want to open the first card of a specific type

    if card.num_channels() < len(CHANNEL_INDICES):
        raise spcm.SpcmException(
            text="This multichannel phase-ramp test needs 8 analog output channels."
        )

    card.card_mode(spcm.SPC_REP_STD_DDS)

    channel_mask = 0
    for channel_index in CHANNEL_INDICES:
        channel_mask |= 1 << channel_index

    channels = spcm.Channels(card, card_enable=channel_mask)
    for channel_index in CHANNEL_INDICES:
        channels[channel_index].enable(True)
        channels[channel_index].output_load(50 * units.ohm)
        channels[channel_index].amp(CHANNEL_RANGE)

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
    dds.trg_timer(DWELL_S)
    actual_dwell_s = dds.get_trg_timer(return_unit=units.s).magnitude

    current_state_name = "A"
    current_phase_list_deg = STATE_A_PHASES_DEG.copy()
    target_phase_list_deg = STATE_B_PHASES_DEG.copy()

    initialize_state(dds, current_phase_list_deg)

    print_section("DDS Multichannel Phase Ramp")
    print(f"Card: {card.product_name()}")
    print(f"External reference: {EXTERNAL_REFERENCE}")
    print(f"Clock input termination: {'50 ohm' if clock.termination() else '5 kohm'}")
    print(f"Actual sample rate: {sample_rate}")
    print(f"Base frequency: {BASE_FREQUENCY}")
    print(f"Selected channels: {CHANNEL_INDICES}")
    print(f"Selected cores: {CORE_INDICES}")
    print(f"DDS frequency step: {DDS_STEP_HZ:.12g} Hz")
    print(f"Phase quantum target: {PHASE_QUANTUM_DEG:.12g} deg")
    print(f"Requested dwell time: {DWELL_S:.12g} s")
    print(f"Actual dwell time:    {actual_dwell_s:.12g} s")
    print(f"State A phases: {STATE_A_PHASES_DEG}")
    print(f"State B phases: {STATE_B_PHASES_DEG}")
    print(
        "Wrapped phase delta A->B: "
        f"{[phase_delta_deg(a, b) for a, b in zip(STATE_A_PHASES_DEG, STATE_B_PHASES_DEG)]}"
    )
    print(
        "Wrapped phase delta B->A: "
        f"{[phase_delta_deg(b, a) for a, b in zip(STATE_A_PHASES_DEG, STATE_B_PHASES_DEG)]}"
    )
    print()
    print("Press any key then Enter to switch states. Type q then Enter to quit.")
    print(f"Current state: {current_state_name} {current_phase_list_deg}")

    card.start(spcm.M2CMD_CARD_ENABLETRIGGER, spcm.M2CMD_CARD_FORCETRIGGER)

    try:
        while True:
            command = input("\nSwitch state (q to quit): ").strip().lower()
            if command in {"q", "quit", "exit"}:
                break

            if current_state_name == "A":
                target_state_name = "B"
                target_phase_list_deg = STATE_B_PHASES_DEG.copy()
            else:
                target_state_name = "A"
                target_phase_list_deg = STATE_A_PHASES_DEG.copy()

            delta_freqs_hz = queue_phase_step(
                dds,
                current_phase_list_deg,
                target_phase_list_deg,
                DWELL_S,
            )

            current_state_name = target_state_name
            current_phase_list_deg = target_phase_list_deg.copy()

            print(f"Switched to state {current_state_name}: {current_phase_list_deg}")
            print(f"Applied frequency offsets: {[round(delta_freq_hz, 12) for delta_freq_hz in delta_freqs_hz]}")
    finally:
        mute_outputs(dds)
        card.stop()
        for channel_index in CHANNEL_INDICES:
            channels[channel_index].enable(False)
        card.write_setup()
        print("Outputs muted and analog channels disabled.")
