"""
Spectrum Instrumentation GmbH (c) 2024

00_dds_frequency_quantization_low_test.py

Interactive low-frequency DDS quantization test for the M2p.65xx DDS option.

This script is intended for use with low-frequency measurement equipment such as
a lock-in amplifier. It probes fine DDS frequency quantization around 300 kHz.
"""

import spcm
from spcm import units


OUTPUT_LEVEL = 100 * units.mV
CHANNEL_RANGE = 500 * units.mV
LOW_FREQUENCY_CENTER_HZ = 300e3
DDS_CLOCK_HZ = 125e6
EXTERNAL_REFERENCE = 10 * units.MHz
CLOCK_TERMINATION_50OHM = False


def print_section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def dedupe_sorted(values: list[float], digits: int = 12) -> list[float]:
    seen = set()
    result = []
    for value in sorted(values):
        key = round(value, digits)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def quantize_to_dds_grid(freq_hz: float, step_hz: float) -> float:
    return round(freq_hz / step_hz) * step_hz


def apply_frequency(dds: spcm.DDS, freq_hz: float) -> float:
    dds[0].freq(freq_hz)
    dds.exec_now()
    dds.write_to_card()
    return dds[0].get_freq()


def mute_output(dds: spcm.DDS) -> None:
    dds[0].amp(0)
    dds.exec_now()
    dds.write_to_card()


def build_offset_requests(
    center_hz: float,
    step_hz: float,
    lower: float,
    upper: float,
    offsets: list[int],
) -> list[float]:
    if step_hz <= 0:
        return [clamp(center_hz, lower, upper)]
    center_hz = quantize_to_dds_grid(center_hz, step_hz)
    return dedupe_sorted(
        [clamp(center_hz + offset * step_hz, lower, upper) for offset in offsets]
    )


card: spcm.Card

# with spcm.Card('/dev/spcm0') as card:                         # if you want to open a specific card
# with spcm.Card('TCPIP::192.168.1.10::inst0::INSTR') as card:  # if you want to open a remote card
# with spcm.Card(serial_number=12345) as card:                  # if you want to open a card by its serial number
with spcm.Card(card_type=spcm.SPCM_TYPE_AO) as card:            # if you want to open the first card of a specific type

    card.card_mode(spcm.SPC_REP_STD_DDS)

    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0)
    channels[0].enable(True)
    channels[0].output_load(50 * units.ohm)
    channels[0].amp(CHANNEL_RANGE)

    clock = spcm.Clock(card)
    clock.mode(spcm.SPC_CM_EXTREFCLOCK)
    clock.reference_clock(EXTERNAL_REFERENCE)
    clock.termination(CLOCK_TERMINATION_50OHM)
    max_sample_rate = clock.max_sample_rate(return_unit=units.Hz)
    actual_sample_rate = clock.sample_rate(max_sample_rate, return_unit=units.Hz)
    clock.clock_output(False)
    card.write_setup()

    dds = spcm.DDS(card, channels=channels)
    dds.reset()
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_NONE)

    dds[0].amp(OUTPUT_LEVEL)
    dds[0].phase(0 * units.degrees)
    dds[0].freq(LOW_FREQUENCY_CENTER_HZ * units.Hz)
    dds.exec_now()
    dds.write_to_card()

    card.start(spcm.M2CMD_CARD_ENABLETRIGGER, spcm.M2CMD_CARD_FORCETRIGGER)

    freq_min = dds.avail_freq_min()
    freq_max = dds.avail_freq_max()
    api_freq_step = dds.avail_freq_step()
    exact_freq_step = DDS_CLOCK_HZ / (2**32)
    quantized_center_hz = quantize_to_dds_grid(LOW_FREQUENCY_CENTER_HZ, exact_freq_step)

    fine_requests = build_offset_requests(
        LOW_FREQUENCY_CENTER_HZ,
        exact_freq_step,
        freq_min,
        freq_max,
        [-3, -2, -1, 0, 1, 2, 3],
    )
    wide_requests = build_offset_requests(
        LOW_FREQUENCY_CENTER_HZ,
        exact_freq_step,
        freq_min,
        freq_max,
        [-32, -16, -8, 0, 8, 16, 32],
    )

    print_section("DDS Low-Frequency Quantization Test")
    print(f"Card: {card.product_name()}")
    print(f"Configured channel range: {CHANNEL_RANGE}")
    print(f"Configured DDS output level: {OUTPUT_LEVEL}")
    print(f"External reference: {EXTERNAL_REFERENCE}")
    print(f"Clock mode: external reference")
    print(f"Clock input termination: {'50 ohm' if clock.termination() else '5 kohm'}")
    print(f"Actual sample rate used: {actual_sample_rate}")
    print(f"API frequency range: {freq_min:.12g} .. {freq_max:.12g} Hz")
    print(f"API frequency step: {api_freq_step:.12g} Hz")
    print(f"Exact frequency step used in this script: {exact_freq_step:.12g} Hz")
    print(f"Quantized 300 kHz center used in this script: {quantized_center_hz:.12g} Hz")
    print()
    print("This script stays near 300 kHz for lock-in based measurements.")
    print("All requested frequencies are exact integer multiples of 125 MHz / 2^32.")
    print("It runs a fine 7-point sweep and then a wider 7-point sweep.")
    print("Press Enter for each step, or type q then Enter to stop.")

    try:
        print_section("Fine Sweep Around 300 kHz")
        for index, request_hz in enumerate(fine_requests, start=1):
            user_input = input(f"\nFine step {index}/{len(fine_requests)} ready? ")
            if user_input.strip().lower() in {"q", "quit", "exit"}:
                break
            readback_hz = apply_frequency(dds, request_hz)
            print(
                f"Requested: {request_hz:.12g} Hz | "
                f"Readback: {readback_hz:.12g} Hz | "
                f"Error: {readback_hz - request_hz:.12g} Hz"
            )
        else:
            print_section("Wider Sweep Around 300 kHz")
            for index, request_hz in enumerate(wide_requests, start=1):
                user_input = input(f"\nWide step {index}/{len(wide_requests)} ready? ")
                if user_input.strip().lower() in {"q", "quit", "exit"}:
                    break
                readback_hz = apply_frequency(dds, request_hz)
                print(
                    f"Requested: {request_hz:.12g} Hz | "
                    f"Readback: {readback_hz:.12g} Hz | "
                    f"Error: {readback_hz - request_hz:.12g} Hz"
                )
    finally:
        mute_output(dds)
        card.stop()
        channels[0].enable(False)
        card.write_setup()
        print()
        print("DDS output muted, card stopped, and channel 0 disabled.")
