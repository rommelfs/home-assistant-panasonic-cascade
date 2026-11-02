"""Conservative temperature stages, not a COP optimiser or power controller."""
import math

# Budget includes existing WP draw, after the battery reserve. This avoids
# withdrawing a stage merely because its own demand reduced grid export.
STAGES = ((45, 3000), (50, 4500), (55, 6000), (60, 8000), (65, 10000))
MAX_OFFSET = 31  # Highest offset verified with buffer-target feedback on hardware.
STAGE_INTERVAL = 600
UP_CONFIRM = 300
DOWN_CONFIRM = 120


def target_bounds(zone, baseline, limit):
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (zone, baseline, limit)):
        raise ValueError('Invalid adaptive target feedback')
    if not 20 <= zone <= 65 or not 0 <= baseline <= 10 or not 40 <= limit <= 65:
        raise ValueError('Adaptive charging requires zone 20–65 °C and limit 40–65 °C')
    return zone + baseline, min(limit, zone + MAX_OFFSET)


def initial_target(budget, zone, baseline, limit):
    low, high = target_bounds(zone, baseline, limit)
    for temperature, required in STAGES:
        if low < temperature <= high and budget >= required:
            return temperature
    raise ValueError('Insufficient PV budget for a supported adaptive temperature stage')


def next_target(budget, current, zone, baseline, limit):
    low, high = target_bounds(zone, baseline, limit)
    candidates = [(t, w) for t, w in STAGES if low < t <= high]
    if not candidates or current > high or current <= low:
        raise ValueError('Zone demand left the adaptive target envelope')
    higher = [(t, w) for t, w in candidates if t > current]
    if higher and budget >= higher[0][1] + 500:
        return higher[0][0]
    required = next((w for t, w in STAGES if t == current), None)
    if required is None:
        raise ValueError('Invalid stored adaptive stage')
    if budget < required - 750:
        lower = [t for t, _ in candidates if t < current]
        if lower:
            return lower[-1]
        raise ValueError('Insufficient PV budget for the lowest adaptive stage')
    return current
