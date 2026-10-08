"""Strategy registry (Phase 1a). Walk-forward, out-of-sample, Monte Carlo and the registry DB come in Phase 1b/1c."""
from strategies.base import BUY, EXIT, WAIT, BaseStrategy
from strategies.trend_following_mirrors import TrendMirrors

STRATEGIES = {
    "trend_mirrors": TrendMirrors,
}

__all__ = ["BUY", "EXIT", "WAIT", "BaseStrategy", "STRATEGIES", "TrendMirrors"]
