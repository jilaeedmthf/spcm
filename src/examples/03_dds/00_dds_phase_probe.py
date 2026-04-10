"""
Spectrum Instrumentation GmbH (c) 2024

00_dds_phase_probe.py

Dedicated DDS phase quantization probe.

This script focuses on three questions:
1. What does the card report via avail_phase_step()?
2. What values does get_phase() return when we request very small phase changes?
3. What is the smallest unique readback increment we can infer from get_phase()?

This is an API/readback-side probe. If the readback remains ambiguous for your
application, the next step is an external measurement with a phase-sensitive
instrument such as a lock-in amplifier.
"""

import spcm
from spcm import units


def print_section(title: str) -> None:
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)


def dedupe_sorted(values: list[float], digits: int = 15) -> list[float]:
    seen = set()
    result = []
    for value in sorted(values):
        key = round(value, digits)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def infer_smallest_increment(values: list[float], digits: int = 15) -> float | None:
    values = dedupe_sorted(values, digits=digits)
    if len(values) < 2:
        return None
    deltas = []
    for first, second in zip(values, values[1:]):
        delta = round(second - first, digits)
        if delta > 0:
            deltas.append(delta)
    if not deltas:
        return None
    return min(deltas)


def apply_phase(dds: spcm.DDS, core_index: int, phase_deg: float) -> float:
    dds[core_index].phase(phase_deg)
    dds.exec_now()
    dds.write_to_card()
    return dds[core_index].get_phase()


card: spcm.Card

# with spcm.Card('/dev/spcm0') as card:                         # if you want to open a specific card
# with spcm.Card('TCPIP::192.168.1.10::inst0::INSTR') as card:  # if you want to open a remote card
# with spcm.Card(serial_number=12345) as card:                  # if you want to open a card by its serial number
with spcm.Card(card_type=spcm.SPCM_TYPE_AO) as card:            # if you want to open the first card of a specific type

    card.card_mode(spcm.SPC_REP_STD_DDS)

    channels = spcm.Channels(card, card_enable=spcm.CHANNEL0)
    channels[0].enable(True)
    channels[0].output_load(50 * units.ohm)
    channels[0].amp(500 * units.mV)
    card.write_setup()

    dds = spcm.DDS(card, channels=channels)
    dds.reset()
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_NONE)

    core_index = 0
    dds[core_index].freq(10 * units.MHz)
    dds[core_index].amp(0.2)
    dds[core_index].phase(0)
    dds.exec_now()
    dds.write_to_card()

    card.start(spcm.M2CMD_CARD_ENABLETRIGGER, spcm.M2CMD_CARD_FORCETRIGGER)

    reported_phase_step = dds.avail_phase_step()
    expected_12bit_step = 360.0 / (2**12)
    expected_10bit_step = 360.0 / (2**10)
    expected_14bit_step = 360.0 / (2**14)

    print_section("Phase Step Summary")
    print(f"Reported phase step: {reported_phase_step:.12g} deg")
    print(f"Candidate 10-bit step: {expected_10bit_step:.12g} deg")
    print(f"Candidate 12-bit step: {expected_12bit_step:.12g} deg")
    print(f"Candidate 14-bit step: {expected_14bit_step:.12g} deg")

    probe_grid = [
        0.0,
        expected_14bit_step,
        2 * expected_14bit_step,
        3 * expected_14bit_step,
        expected_12bit_step / 4,
        expected_12bit_step / 2,
        3 * expected_12bit_step / 4,
        expected_12bit_step,
        expected_10bit_step / 4,
        expected_10bit_step / 2,
        3 * expected_10bit_step / 4,
        expected_10bit_step,
    ]
    probe_grid = dedupe_sorted(probe_grid)

    print_section("Fine Phase Probe Near 0 Degrees")
    print(f"{'request_deg':>18} {'readback_deg':>18} {'error_deg':>18}")
    near_zero_readbacks = []
    for phase_deg in probe_grid:
        readback = apply_phase(dds, core_index, phase_deg)
        near_zero_readbacks.append(readback)
        print(f"{phase_deg:18.12g} {readback:18.12g} {readback - phase_deg:18.12g}")

    inferred_near_zero = infer_smallest_increment(near_zero_readbacks)
    print()
    print(f"Unique near-zero readbacks: {dedupe_sorted(near_zero_readbacks)}")
    print(f"Inferred smallest near-zero increment: {inferred_near_zero}")

    dense_requests = [index * 0.01 for index in range(0, 51)]
    dense_readbacks = []
    print_section("Dense 0.01 Degree Sweep Over 0..0.5 Degrees")
    print(f"{'request_deg':>18} {'readback_deg':>18} {'error_deg':>18}")
    for phase_deg in dense_requests:
        readback = apply_phase(dds, core_index, phase_deg)
        dense_readbacks.append(readback)
        print(f"{phase_deg:18.12g} {readback:18.12g} {readback - phase_deg:18.12g}")

    unique_dense = dedupe_sorted(dense_readbacks)
    inferred_dense = infer_smallest_increment(unique_dense)
    print()
    print(f"Number of unique readbacks in dense sweep: {len(unique_dense)}")
    print(f"Unique dense readbacks: {unique_dense}")
    print(f"Inferred smallest dense-sweep increment: {inferred_dense}")

    anchor_requests = [
        0.0,
        45.0 - expected_14bit_step,
        45.0,
        45.0 + expected_14bit_step,
        90.0 - expected_14bit_step,
        90.0,
        90.0 + expected_14bit_step,
        180.0 - expected_14bit_step,
        180.0,
        180.0 + expected_14bit_step,
    ]
    anchor_requests = dedupe_sorted(anchor_requests)

    print_section("Anchor Checks Around 45, 90, and 180 Degrees")
    print(f"{'request_deg':>18} {'readback_deg':>18} {'error_deg':>18}")
    for phase_deg in anchor_requests:
        readback = apply_phase(dds, core_index, phase_deg)
        print(f"{phase_deg:18.12g} {readback:18.12g} {readback - phase_deg:18.12g}")

    dds[core_index].amp(0.0)
    dds.exec_now()
    dds.write_to_card()

    print()
    print("DDS phase probe complete. Core 0 amplitude has been muted.")
    input("Press Enter to Exit")
