"""
Outcome Tracker — kalibrasi sinyal screener ke kenyataan (Tugas D).

Melacak apa yang terjadi SETELAH tiap sinyal keluar: harga entry, return
T+1/T+3/T+5, lalu menskor win-rate per verdict. Dipakai oleh bot
idx-bandarmologi pada tiap run harian, dan dibaca weekly report.

Alur:
  1. ingest_signals()  — daftarkan sinyal baru dari export/*.json ke outcomes.json
  2. update_outcomes() — isi entry_price & return T+1/3/5 via fetch_price
                         (callback ke Invezgo; tracker ini agnostik sumber)
  3. score()           — hit-rate & avg return per verdict, kalibrasi confidence

Aturan skor:
  - APPROVE  = WIN  jika return T+5 > 0
  - REJECT   = BENAR jika return T+5 <= 0 (bot benar menghindari)
  - NEUTRAL  = tidak diskor, hanya dicatat
  - Sinyal CLOSED setelah T+5 terisi. Win-rate dihitung HANYA dari CLOSED.
"""

from __future__ import annotations

import json
import glob
import os
from datetime import date, timedelta
from typing import Callable

OUTCOMES_PATH = "export/outcomes.json"
EXPORT_GLOB = "export/2*.json"  # file sinyal harian (bukan outcomes.json)
HORIZONS = (1, 3, 5)  # hari bursa setelah sinyal


# ── persistence ─────────────────────────────────────────────────────────

def load_outcomes(path: str = OUTCOMES_PATH) -> dict:
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"outcomes": {}}


def save_outcomes(data: dict, path: str = OUTCOMES_PATH) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _key(ticker: str, signal_date: str) -> str:
    return f"{signal_date}:{ticker}"


# ── 1. ingest ───────────────────────────────────────────────────────────

def ingest_signals(outcomes: dict, export_glob: str = EXPORT_GLOB) -> int:
    """Daftarkan sinyal dari file export harian yang belum ada di tracker.
    Return: jumlah entry baru."""
    added = 0
    for path in sorted(glob.glob(export_glob)):
        with open(path) as f:
            day = json.load(f)
        sig_date = day.get("date")
        for ticker, sig in day.get("signals", {}).items():
            k = _key(ticker, sig_date)
            if k in outcomes["outcomes"]:
                continue
            outcomes["outcomes"][k] = {
                "ticker": ticker,
                "signal_date": sig_date,
                "verdict": sig.get("verdict"),
                "confidence": sig.get("confidence"),
                "entry_price": None,          # diisi update_outcomes (Invezgo)
                "returns": {f"t{h}": None for h in HORIZONS},
                "status": "OPEN",
            }
            added += 1
    return added


# ── 2. update ───────────────────────────────────────────────────────────

def update_outcomes(outcomes: dict,
                    fetch_price: Callable[[str, str], float | None],
                    today: str) -> int:
    """Isi entry_price & return utk sinyal OPEN.

    fetch_price(ticker, iso_date) -> harga close pada tanggal itu, atau None
    bila tidak tersedia (hari libur -> caller boleh geser ke hari bursa
    berikutnya sebelum memanggil; tracker menganggap None = belum ada data).
    today: tanggal run saat ini (ISO), utk tahu horizon mana yang sudah lewat.
    """
    updated = 0
    t_now = date.fromisoformat(today)
    for k, o in outcomes["outcomes"].items():
        if o["status"] != "OPEN":
            continue
        d0 = date.fromisoformat(o["signal_date"])
        changed = False

        if o["entry_price"] is None:
            px = fetch_price(o["ticker"], o["signal_date"])
            if px:
                o["entry_price"] = px
                changed = True

        if o["entry_price"]:
            for h in HORIZONS:
                slot = f"t{h}"
                target = d0 + timedelta(days=h)
                if o["returns"][slot] is None and t_now >= target:
                    px = fetch_price(o["ticker"], target.isoformat())
                    if px:
                        o["returns"][slot] = round(
                            (px - o["entry_price"]) / o["entry_price"] * 100, 2)
                        changed = True

        if o["returns"][f"t{HORIZONS[-1]}"] is not None:
            o["status"] = "CLOSED"
            changed = True
        if changed:
            updated += 1
    return updated


# ── 3. skor ─────────────────────────────────────────────────────────────

def score(outcomes: dict) -> dict:
    """Statistik per verdict dari sinyal CLOSED + kalibrasi confidence."""
    closed = [o for o in outcomes["outcomes"].values()
              if o["status"] == "CLOSED"]
    stats: dict = {"closed": len(closed),
                   "open": sum(1 for o in outcomes["outcomes"].values()
                               if o["status"] == "OPEN")}

    def bucket(verdict: str) -> list[dict]:
        return [o for o in closed if o["verdict"] == verdict]

    for verdict, win_fn in (("APPROVE", lambda r: r > 0),
                            ("REJECT", lambda r: r <= 0)):
        rows = bucket(verdict)
        n = len(rows)
        if n == 0:
            stats[verdict] = {"n": 0, "hit_rate": None, "avg_t5": None}
            continue
        wins = [o for o in rows if win_fn(o["returns"]["t5"])]
        stats[verdict] = {
            "n": n,
            "hit_rate": round(len(wins) / n * 100, 1),
            "avg_t5": round(sum(o["returns"]["t5"] for o in rows) / n, 2),
            "avg_conf_benar": round(sum(o["confidence"] for o in wins)
                                    / len(wins), 1) if wins else None,
            "avg_conf_salah": round(sum(o["confidence"] for o in rows
                                        if o not in wins)
                                    / (n - len(wins)), 1) if n > len(wins) else None,
        }
    stats["NEUTRAL"] = {"n": len(bucket("NEUTRAL"))}
    return stats


def format_weekly_section(stats: dict) -> str:
    """Blok teks utk weekly report (nyambung fix #9: closed==0 -> N/A)."""
    lines = ["━━ 🎯 OUTCOME TRACKER ━━",
             f"Closed: {stats['closed']} | Open: {stats['open']}"]
    if stats["closed"] == 0:
        lines.append("Win rate: N/A — belum ada sinyal closed")
        lines.append("ℹ️ Evaluasi dimulai setelah sinyal mencapai T+5")
        return "\n".join(lines)
    for v, label in (("APPROVE", "✅ APPROVE"), ("REJECT", "❌ REJECT")):
        s = stats[v]
        if s["n"] == 0:
            lines.append(f"{label}: belum ada sampel closed")
        else:
            lines.append(f"{label}: hit {s['hit_rate']}% (n={s['n']}) "
                         f"| avg T+5 {s['avg_t5']:+.2f}%")
    return "\n".join(lines)


# ── CLI: ingest sinyal historis repo ini (backfill entry tanpa harga) ───

if __name__ == "__main__":
    data = load_outcomes()
    n = ingest_signals(data)
    save_outcomes(data)
    print(f"Ingest: {n} sinyal baru terdaftar -> {OUTCOMES_PATH}")
    stats = score(data)
    print(format_weekly_section(stats))
