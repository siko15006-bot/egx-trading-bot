"""H3 AI Score forward test — the protocol in docs/research/H3_ai_score.md ("Forward test protocol").

Daily (scheduled task EGX_H3_Forward): if 21 production sessions have passed since the last rebalance (or none yet),
download the 403 candidates fully adjusted into data_h3_live/, score them with the frozen model, store the top 10
and the 60-stock pool in `h3_forward`, evaluate completed periods (ideal and realistic) and send one Telegram message.
Not investment advice; no real money until the 12-period verdict and Ahmed's decision.
Run: python h3_forward.py [--force]   |   python h3_forward.py --test
"""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import numpy as np
import pandas as pd

import egx_4_mirrors_v3 as eng
import research_h1_momentum as h1
import research_h3_ai_score as h3
from paper_trading import _db_path
from telegram_notifier import send_telegram

HERE = Path(__file__).parent
LIVE = HERE / "data_h3_live"
MODEL = json.loads((HERE / "docs" / "research" / "H3_model.json").read_text(encoding="utf-8"))
EVERY, TOP_N, FEE, KILL = 21, 10, 0.003, -0.10
LABEL = "🧠 H3 AI Score — متابعة بدون فلوس (المستوى 1 معلّق). مش إشارة مثبتة ومش نصيحة استثمار."


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(_db_path())
    con.execute("""CREATE TABLE IF NOT EXISTS h3_forward (rebalance TEXT NOT NULL, ticker TEXT NOT NULL,
        rank INTEGER, score REAL NOT NULL, top10 INTEGER NOT NULL, PRIMARY KEY (rebalance, ticker))""")
    return con


def sessions() -> list[str]:
    """Production EGX calendar: every date present in data/ (updated daily by daily_runner)."""
    days: set[str] = set()
    for f in (HERE / "data").glob("*.csv"):
        days |= set(pd.read_csv(f, usecols=["Date"])["Date"].astype(str).str[:10])
    return sorted(days)


def due(today: str, last: str | None, cal: list[str]) -> bool:
    return last is None or sum(last < d <= today for d in cal) >= EVERY


def score_pool(close: pd.DataFrame, value: pd.DataFrame, is_real: pd.DataFrame) -> pd.DataFrame:
    """Frozen-model scores for the eligible pool on the last row of the panel."""
    d = h3.dataset(close, value, is_real, positions=[len(close) - 1])
    x = (d[MODEL["features"]].to_numpy() - np.array(MODEL["mean"])) / np.array(MODEL["scale"])
    d["score"] = 1 / (1 + np.exp(-(x @ np.array(MODEL["coef"]) + MODEL["intercept"])))
    d = d.reset_index().rename(columns={"index": "ticker"}).sort_values(["score", "ticker"], ascending=[False, True])
    d["rank"] = range(1, len(d) + 1)
    d["top10"] = (d["rank"] <= TOP_N).astype(int)
    return d[["ticker", "rank", "score", "top10"]]


def evaluate(book: pd.DataFrame, closes: pd.DataFrame) -> pd.DataFrame:
    """Per completed period: top-10 and EW pool returns, ideal (close of the rebalance day → close of the next) and
    realistic (close of the session after → close of the session after the next rebalance). No Open: Yahoo's EGX Open
    is not a real opening price. Stocks with a >25% data break inside the period are left out of both averages."""
    dates = sorted(book["rebalance"].unique())
    idx = closes.index.strftime("%Y-%m-%d").tolist()
    jumps = closes.pct_change(fill_method=None).abs() > eng.MAX_DAILY_MOVE
    rows = []
    for a, b in zip(dates, dates[1:]):
        if a not in idx or b not in idx:  # a Yahoo revision dropped the session: skip rather than guess
            continue
        g = book[book["rebalance"] == a]
        ia, ib = idx.index(a), idx.index(b)
        row = {"period": f"{a}→{b}"}
        for kind, i0, i1 in (("ideal", ia, ib), ("real", ia + 1, ib + 1)):
            if i1 >= len(closes):
                continue  # realistic period completes one session after the next rebalance
            ret = (closes.iloc[i1] / closes.iloc[i0] - 1)[~jumps.iloc[i0 + 1:i1 + 1].any()]
            row[f"{kind}_top10"] = float(ret.reindex(g.loc[g["top10"] == 1, "ticker"]).mean()) - FEE
            row[f"{kind}_ew"] = float(ret.reindex(g["ticker"]).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def summary(ev: pd.DataFrame) -> tuple[str, bool]:
    if ev.empty or "real_top10" not in ev or ev["real_top10"].isna().all():
        return "لسه مفيش فترة مكتملة بالتنفيذ الواقعي.", False
    done = ev.dropna(subset=["real_top10"])
    top, ew = (1 + done["real_top10"]).prod() - 1, (1 + done["real_ew"]).prod() - 1
    kill = top - ew <= KILL
    return (f"فترات مكتملة (واقعي): {len(done)}/12 | Top10 {top:+.1%} | المحفظة المتساوية {ew:+.1%} | الفرق {top - ew:+.1%}"
            + ("\n⛔ وصل لحد الإيقاف (−10 نقاط) — المتابعة تقف حسب الوثيقة." if kill else "")), kill


def main(force: bool = False) -> int:
    cal = sessions()
    today = cal[-1]
    with closing(_con()) as con:
        last = con.execute("SELECT MAX(rebalance) FROM h3_forward").fetchone()[0]
        if not (force or due(today, last, cal)):
            print(f"not due: last rebalance {last}, today {today}")
            return 0
        h1.OUT = LIVE
        h1.download()
        close, value, is_real = h1.load_panels(LIVE)
        close, value, is_real = (x.loc[:today] for x in (close, value, is_real))
        rebalance = close.index[-1].strftime("%Y-%m-%d")
        picks = score_pool(close, value, is_real)
        con.executemany("INSERT OR REPLACE INTO h3_forward VALUES (?, ?, ?, ?, ?)",
                        [(rebalance, r.ticker, int(r.rank), float(r.score), int(r.top10)) for r in picks.itertuples()])
        con.commit()
        book = pd.read_sql_query("SELECT * FROM h3_forward", con)
    stats, kill = summary(evaluate(book, close.ffill()))
    top = picks[picks["top10"] == 1]
    lines = "\n".join(f"{int(r.rank)}. {r.ticker.replace('.CA', '')} ({r.score:.2f})" for r in top.itertuples())
    send_telegram(f"{LABEL}\nإعادة ترتيب: {rebalance} — أعلى 10 من {len(picks)} سهم سيولة:\n{lines}\n\n{stats}")
    print(f"rebalance {rebalance}: {len(picks)} scored, kill={kill}")
    return 0


def _selftest() -> None:
    cal = [f"2026-01-{d:02d}" for d in range(1, 31)]
    assert due("2026-01-05", None, cal) and not due("2026-01-21", "2026-01-01", cal) and due("2026-01-22", "2026-01-01", cal)
    idx = pd.date_range("2026-01-01", periods=5)
    closes = pd.DataFrame({"A": [10, 11, 12, 12, 13], "B": [10, 10, 9, 9, 8], "C": [10, 10, 30, 30, 30]}, index=idx, dtype=float)
    book = pd.DataFrame({"rebalance": ["2026-01-01"] * 3 + ["2026-01-03"] * 3, "ticker": ["A", "B", "C"] * 2,
                         "top10": [1, 0, 1, 1, 0, 1]})
    ev = evaluate(book, closes).iloc[0]   # C jumps +200% (data break) → excluded from both averages
    assert abs(ev["ideal_top10"] - (0.2 - FEE)) < 1e-12 and abs(ev["ideal_ew"] - 0.05) < 1e-12
    assert abs(ev["real_top10"] - (12 / 11 - 1 - FEE)) < 1e-12 and abs(ev["real_ew"] - ((12 / 11 - 1) + (9 / 10 - 1)) / 2) < 1e-12
    text, kill = summary(pd.DataFrame([{"real_top10": -0.2, "real_ew": 0.0}]))
    assert kill and "⛔" in text
    print("h3_forward self-test OK")


if __name__ == "__main__":
    if "--test" in sys.argv:
        _selftest()
        raise SystemExit(0)
    raise SystemExit(main("--force" in sys.argv))
