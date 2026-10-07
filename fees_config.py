"""Current Thndr cash-equity tariff; a scenario, not a historical fee archive."""
from dataclasses import dataclass
from math import isfinite

SOURCE_URL = 'https://support.thndr.app/en/articles/638558-thndr-order-fees'
LEGACY_CORE_FEE_PER_SIDE = 0.003  # Previous v3 assumption, NOT a Thndr tariff.


@dataclass(frozen=True)
class FeesConfig:
    # All tariff fields below: SOURCE_URL, accessed 2026-10-07.
    brokerage_fixed_egp: float = 2.0
    brokerage_variable_pct: float = 0.001
    egx_pct: float = 0.0001
    egx_max_egp: float = 5000.0
    mcdr_pct: float = 0.0001
    mcdr_max_egp: float = 5000.0
    fra_pct: float = 0.00005
    fra_min_egp: float = 1.0
    fra_max_egp: float = 250.0
    insurance_pct: float = 0.00005
    insurance_max_egp: float = 5000.0
    stamp_t0_pct: float = 0.00025
    stamp_overnight_pct: float = 0.0005

    def __post_init__(self):
        if any(not isfinite(v) or v < 0 for v in vars(self).values()):
            raise ValueError('Fee parameters must be finite and nonnegative')
        if self.fra_min_egp > self.fra_max_egp:
            raise ValueError('FRA minimum exceeds maximum')


THNDR_FEES = FeesConfig()


def order_fees(value, *, same_session=False, fills=None, config=THNDR_FEES):
    """Final fees after T0 refund; fills are executed notionals, not a fill model."""
    value = float(value)
    if not isfinite(value) or value <= 0:
        raise ValueError('Executed order value must be finite and positive')
    # ponytail: one transaction per order by default; pass actual fills when available.
    fills = (value,) if fills is None else tuple(float(v) for v in fills)
    if not fills or any(not isfinite(v) or v <= 0 for v in fills):
        raise ValueError('Fill notionals must be finite and positive')
    if abs(sum(fills) - value) > max(1e-8, value * 1e-12):
        raise ValueError('Fill notionals must sum to executed order value')
    c = config
    return {
        'brokerage': c.brokerage_fixed_egp + value * c.brokerage_variable_pct,
        'egx': min(value * c.egx_pct, c.egx_max_egp),
        'mcdr': min(value * c.mcdr_pct, c.mcdr_max_egp),
        'fra': sum(min(max(v * c.fra_pct, c.fra_min_egp), c.fra_max_egp) for v in fills),
        'insurance': min(value * c.insurance_pct, c.insurance_max_egp),
        'stamp': value * (c.stamp_t0_pct if same_session else c.stamp_overnight_pct),
    }


def round_trip_fees(entry_value, exit_value, *, same_session=False,
                    entry_fills=None, exit_fills=None, config=THNDR_FEES):
    return sum(order_fees(entry_value, same_session=same_session, fills=entry_fills, config=config).values()) + sum(
        order_fees(exit_value, same_session=same_session, fills=exit_fills, config=config).values())
