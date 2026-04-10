"""
Spectrum Instrumentation GmbH (c) 2024

00_dds_quantization_probe.py

Probe DDS quantization behavior on one core using the card's reported DDS step
sizes and the DDS get_* readback functions.

This script focuses on:
- frequency quantization
- amplitude quantization in raw fraction units
- phase quantization

Notes
-----
- Amplitude is tested in fraction units on purpose, to avoid confusion from
  output-load dependent voltage conversion.
- The script uses the DDS get_* functions as the measured value source.
- Timing quantization for the pulse generator is intentionally left for a later
  dedicated script.
- For M2p.6533 the datasheet-derived reference values are:
  frequency step = max_sample_rate / 2^32
  amplitude step = 1 / (2^15 - 1)
  phase step = 360 / 2^12 degrees

See the README file in the parent folder of this examples directory for
information about how to use this example.

See the LICENSE file for the conditions under which this software may be used
and distributed.
"""

import spcm
from spcm import units


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def safe_step(value: float) -> float:
    return value if value and value > 0 else 0.0


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


def rel_close(a: float, b: float, rel_tol: float = 1e-12, abs_tol: float = 0.0) -> bool:
    return abs(a - b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)


def format_ratio(numerator: float, denominator: float) -> str:
    if denominator <= 0:
        return "n/a"
    return f"{numerator / denominator:.6f}"


def apply_core_state(dds: spcm.DDS, core_index: int, freq_hz: float, amp_frac: float, phase_deg: float) -> tuple[float, float, float]:
    dds[core_index].freq(freq_hz)
    dds[core_index].amp(amp_frac)
    dds[core_index].phase(phase_deg)
    dds.exec_now()
    dds.write_to_card()
    return (
        dds[core_index].get_freq(),
        dds[core_index].get_amp(),
        dds[core_index].get_phase(),
    )


def sweep_parameter(
    label: str,
    requests: list[float],
    apply_value,
    readback_value,
    reported_step: float,
    expected_step: float,
    unit_label: str,
) -> None:
    print_section(label)
    print(f"Expected step: {expected_step:.12g} {unit_label}")
    if reported_step > 0:
        print(f"Reported step: {reported_step:.12g} {unit_label}")
        print(f"Reported/expected: {format_ratio(reported_step, expected_step)}")
    else:
        print("Reported step: unavailable or zero")
    print()
    print(
        f"{'request':>18} {'readback':>18} {'error':>18} "
        f"{'err/rep_step':>18} {'err/exp_step':>18}"
    )
    for request in requests:
        apply_value(request)
        readback = readback_value()
        error = readback - request
        if reported_step > 0:
            error_in_reported_steps = f"{error / reported_step:18.6f}"
        else:
            error_in_reported_steps = f"{'n/a':>18}"
        error_in_expected_steps = (
            f"{error / expected_step:18.6f}" if expected_step > 0 else f"{'n/a':>18}"
        )
        print(
            f"{request:18.12g} {readback:18.12g} {error:18.12g} "
            f"{error_in_reported_steps} {error_in_expected_steps}"
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
    channels[0].amp(500 * units.mV)
    clock = spcm.Clock(card)
    card.write_setup()

    dds = spcm.DDS(card, channels=channels)
    dds.reset()
    dds.trg_src(spcm.SPCM_DDS_TRG_SRC_NONE)

    core_index = 0

    # Establish a stable initial state before probing quantization.
    apply_core_state(dds, core_index, 10e6, 0.2, 0.0)
    card.start(spcm.M2CMD_CARD_ENABLETRIGGER, spcm.M2CMD_CARD_FORCETRIGGER)

    freq_min = dds.avail_freq_min()
    freq_max = dds.avail_freq_max()
    freq_step = safe_step(dds.avail_freq_step())
    max_sample_rate = clock.max_sample_rate()
    expected_freq_step = max_sample_rate / (2**32)

    amp_min = dds.avail_amp_min()
    amp_max = dds.avail_amp_max()
    amp_step = safe_step(dds.avail_amp_step())
    expected_amp_step = 1.0 / ((2**15) - 1)

    phase_min = dds.avail_phase_min()
    phase_max = dds.avail_phase_max()
    phase_step = safe_step(dds.avail_phase_step())
    expected_phase_step = 360.0 / (2**12)

    print_section("DDS Quantization Summary")
    print(f"Card max sample rate: {max_sample_rate} Hz")
    print()
    print(
        "Frequency min/max/reported-step/expected-step: "
        f"{freq_min:.12g} / {freq_max:.12g} / {freq_step:.12g} / {expected_freq_step:.12g} Hz"
    )
    print(
        "Amplitude min/max/reported-step/expected-step: "
        f"{amp_min:.12g} / {amp_max:.12g} / {amp_step:.12g} / {expected_amp_step:.12g} fraction"
    )
    print(
        "Phase min/max/reported-step/expected-step: "
        f"{phase_min:.12g} / {phase_max:.12g} / {phase_step:.12g} / {expected_phase_step:.12g} deg"
    )
    print()
    print("Reported-vs-datasheet checks:")
    print(
        f"  Frequency step match: {rel_close(freq_step, expected_freq_step, abs_tol=expected_freq_step * 1e-9)}"
    )
    print(
        f"  Amplitude step match: {rel_close(amp_step, expected_amp_step, abs_tol=expected_amp_step * 1e-9)}"
    )
    print(
        f"  Phase step match: {rel_close(phase_step, expected_phase_step, abs_tol=expected_phase_step * 1e-9)}"
    )

    freq_centers = [1e6, 10e6, 25e6]
    freq_offsets = [-1.25, -0.5, -0.25, 0.0, 0.25, 0.5, 1.25]
    if expected_freq_step > 0:
        freq_requests = [
            clamp(center + offset * expected_freq_step, freq_min, freq_max)
            for center in freq_centers
            for offset in freq_offsets
        ]
    else:
        freq_requests = [1e6, 10e6, 25e6]
    freq_requests = dedupe_sorted(freq_requests)

    amp_centers = [0.02, 0.1, 0.25, 0.5]
    amp_offsets = [-1.25, -0.5, -0.25, 0.0, 0.25, 0.5, 1.25]
    if expected_amp_step > 0:
        amp_requests = [
            clamp(center + offset * expected_amp_step, amp_min, amp_max)
            for center in amp_centers
            for offset in amp_offsets
        ]
    else:
        amp_requests = [0.02, 0.1, 0.25, 0.5]
    amp_requests = dedupe_sorted(amp_requests)

    phase_centers = [0.0, 45.0, 180.0]
    phase_offsets = [-1.25, -0.5, -0.25, 0.0, 0.25, 0.5, 1.25]
    if expected_phase_step > 0:
        phase_requests = [
            clamp(center + offset * expected_phase_step, phase_min, phase_max)
            for center in phase_centers
            for offset in phase_offsets
        ]
    else:
        phase_requests = [0.0, 45.0, 180.0]
    phase_requests = dedupe_sorted(phase_requests)

    sweep_parameter(
        "Frequency Quantization",
        freq_requests,
        lambda value: apply_core_state(dds, core_index, value, dds[core_index].get_amp(), dds[core_index].get_phase()),
        lambda: dds[core_index].get_freq(),
        freq_step,
        expected_freq_step,
        "Hz",
    )

    sweep_parameter(
        "Amplitude Quantization (fraction)",
        amp_requests,
        lambda value: apply_core_state(dds, core_index, dds[core_index].get_freq(), value, dds[core_index].get_phase()),
        lambda: dds[core_index].get_amp(),
        amp_step,
        expected_amp_step,
        "fraction",
    )

    sweep_parameter(
        "Phase Quantization",
        phase_requests,
        lambda value: apply_core_state(dds, core_index, dds[core_index].get_freq(), dds[core_index].get_amp(), value),
        lambda: dds[core_index].get_phase(),
        phase_step,
        expected_phase_step,
        "deg",
    )

    # Clean up by muting the core before leaving the example.
    apply_core_state(dds, core_index, dds[core_index].get_freq(), 0.0, dds[core_index].get_phase())
    print()
    print("DDS quantization probe complete. Core 0 amplitude has been muted.")
    input("Press Enter to Exit")
