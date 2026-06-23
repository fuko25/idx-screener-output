"""
Drop-in perbaikan untuk IDX Analisa Bot (idx-bandarmologi).

Berisi implementasi yang sudah diperbaiki untuk 9 bug yang ditemukan dari
output analisa (GJTL, TSPC, IATA) + weekly report. Fungsi-fungsi di sini
self-contained — tinggal panggil dari formatter/report bot, atau jadikan
acuan untuk patch presisi.

Mapping bug -> fungsi:
  #1 verdict kepotong            -> clip_insight()
  #2 fib ladder salah posisi     -> render_fib_ladder()
  #3 satuan lot vs shares        -> compute_value() / LOT_SIZE
  #4 VA20 ratio implausibel      -> compute_va20_ratio()
  #5 orderbook label "lemah"     -> orderbook_label()
  #6 trend SIDEWAYS vs EMA       -> classify_trend()
  #7 RSI 50.0 fallback           -> safe_rsi()
  #8 gate verbosity by verdict   -> render_analysis()
  #9 weekly win-rate 0/0         -> weekly_winrate() / weekly_insight()
"""

from __future__ import annotations

LOT_SIZE = 100  # 1 lot = 100 lembar (IDX)


# ── #3 & #4: SATUAN VOLUME ──────────────────────────────────────────────
# Akar masalah: nilai transaksi dihitung seakan volume = lembar, tapi
# field-nya dilabeli "lot". Tetapkan SATU sumber kebenaran: simpan volume
# dalam LOT, lalu konversi ke lembar saat hitung nilai (× LOT_SIZE × harga).
# Kalau data mentah ternyata sudah lembar, set vol_lot = shares / LOT_SIZE.

def compute_value(vol_lot: float, price: float) -> float:
    """Nilai transaksi (Rp) = lot × 100 lembar × harga."""
    return vol_lot * LOT_SIZE * price


def compute_va20_ratio(vol_today_lot: float, avg20_lot: float) -> float | None:
    """Ratio volume hari ini vs rata-rata 20 hari.
    PENTING: kedua argumen harus satuan sama (dua-duanya lot). Mismatch
    lot-vs-lembar = ratio meledak 100x (sumber VA20 118x/240x yang aneh).
    """
    if not avg20_lot or avg20_lot <= 0:
        return None
    return vol_today_lot / avg20_lot


# ── #2: FIBONACCI LADDER ────────────────────────────────────────────────
# Bug: baris "Harga NOW" selalu disisipkan di slot tetap (setelah R0.500),
# bukan diurutkan menurut nilai. Fix: gabung semua baris lalu sort desc.

def render_fib_ladder(levels: dict[str, float], price: float,
                      golden_key: str = "R 0.618",
                      support_key: str = "Support") -> str:
    """
    levels: {"R 0.786": 70, "R 0.618": 66, ... "Support": 51}
    Sisipkan harga NOW pada posisi yang benar (urut nilai menurun).
    """
    rows = [(label, val) for label, val in levels.items()]
    rows.append(("Harga", price))  # NOW sebagai baris biasa, lalu di-sort
    rows.sort(key=lambda kv: kv[1], reverse=True)

    out = []
    for label, val in rows:
        tag = ""
        if label == "Harga":
            tag = " <- NOW"
        elif label == golden_key:
            tag = " <- Golden"
        out.append(f"{label:<8}: Rp {val:>10,.0f}{tag}")
    return "\n".join(out)


def fib_position_note(levels: dict[str, float], price: float) -> str:
    """Keterangan posisi harga relatif ke level fib (sudah benar di bot,
    disertakan agar konsisten dengan ladder)."""
    ordered = sorted(levels.items(), key=lambda kv: kv[1], reverse=True)
    top_label, top_val = ordered[0]
    if price >= top_val:
        return f"Di atas {top_label} — RESISTANCE KUAT"
    for (hi_l, hi_v), (lo_l, lo_v) in zip(ordered, ordered[1:]):
        if lo_v <= price <= hi_v:
            return f"Di antara {lo_l}-{hi_l}"
    return f"Di bawah {ordered[-1][0]} — area support"


# ── #5: ORDER BOOK LABEL ────────────────────────────────────────────────
# Bug: 0.97 ditampilkan "1.0x" tapi diberi label "lemah". Pakai NILAI ASLI
# untuk threshold, dan tampilkan 2 desimal biar konsisten dengan flag.

def orderbook_label(bid_lot: float, offer_lot: float) -> tuple[str, str]:
    if offer_lot <= 0:
        return ("n/a", "")
    ratio = bid_lot / offer_lot
    if ratio >= 1.5:
        flag = "kuat 💪"
    elif ratio >= 0.8:          # 0.8–1.5 = seimbang, BUKAN "lemah"
        flag = "seimbang"
    else:
        flag = "lemah ⚠️"
    return (f"{ratio:.2f}x", flag)


# ── #6: KLASIFIKASI TREND ───────────────────────────────────────────────
# Bug: trend dilabeli "SIDEWAYS" padahal EMA20 < EMA50 (bearish). Tentukan
# trend dari hubungan EMA + posisi harga, bukan default.

def classify_trend(price: float, ema20: float, ema50: float,
                   tol: float = 0.005) -> str:
    spread = (ema20 - ema50) / ema50 if ema50 else 0
    if spread > tol and price >= ema20:
        return "UPTREND ↗"
    if spread < -tol and price <= ema20:
        return "DOWNTREND ↘"
    if spread < -tol:
        return "DOWNTREND (lemah) ↘"  # EMA bearish walau harga di atas EMA20
    if spread > tol:
        return "UPTREND (lemah) ↗"
    return "SIDEWAYS →"


# ── #7: RSI FALLBACK ────────────────────────────────────────────────────
# Bug: RSI tepat 50.0 dicurigai placeholder saat data kurang. Jangan
# pura-pura 50; tandai eksplisit kalau tak bisa dihitung.

def safe_rsi(rsi_value: float | None, periods_available: int,
             min_periods: int = 14) -> str:
    if rsi_value is None or periods_available < min_periods:
        return "n/a (data <14H)"
    label = "Normal ✅" if 30 <= rsi_value <= 70 else (
        "Overbought ⚠️" if rsi_value > 70 else "Oversold ⚠️")
    return f"{rsi_value:.1f} {label}"


# ── #1: TRUNCATION VERDICT/INSIGHT ──────────────────────────────────────
# Bug: insight dipotong pakai slice mentah (text[:N]) -> putus di tengah
# kata. Potong di batas kalimat, kasih elipsis kalau perlu.

def clip_insight(text: str, max_len: int = 350) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    # mundur ke akhir kalimat terakhir; fallback ke spasi
    for sep in (". ", "! ", "? "):
        idx = cut.rfind(sep)
        if idx > max_len * 0.5:
            return cut[:idx + 1].strip()
    return cut[:cut.rfind(" ")].rstrip() + "…"


# ── #8: GATE VERBOSITY BY VERDICT ───────────────────────────────────────
# REJECT -> one-liner. NEUTRAL -> ringkas. APPROVE -> full detail.
# (full_block = string laporan lengkap yang sudah dirender bot.)

def render_analysis(verdict: str, ticker: str, confidence: int,
                    insight: str, full_block: str,
                    key_levels: str = "") -> str:
    v = verdict.upper()
    insight = clip_insight(insight)
    if v == "REJECT":
        return f"❌ {ticker} REJECT ({confidence}%) — {clip_insight(insight, 120)}"
    if v == "NEUTRAL":
        head = f"🟡 {ticker} NEUTRAL ({confidence}%)"
        body = f"\n{key_levels}" if key_levels else ""
        return f"{head}\n💡 {insight}{body}"
    # APPROVE -> full
    return full_block


# ── #9: WEEKLY REPORT WIN-RATE ──────────────────────────────────────────
# Bug: 0 wins / 0 closed disajikan 0.0% dan memicu "🚨 audit setup".
# Win rate undefined kalau closed == 0 -> tampil "N/A", insight beda.

MIN_SAMPLE = 5  # minimal trade closed sebelum win-rate dianggap bermakna

def weekly_winrate(wins: int, closed: int) -> float | None:
    return (wins / closed) if closed > 0 else None

def format_winrate(wins: int, closed: int) -> str:
    wr = weekly_winrate(wins, closed)
    return "N/A" if wr is None else f"{wr * 100:.1f}%"

def weekly_insight(wins: int, closed: int, win_threshold: float = 0.5) -> str:
    if closed == 0:
        return "ℹ️ Belum ada posisi closed — win rate belum bisa dinilai"
    wr = wins / closed
    if closed < MIN_SAMPLE:
        return (f"ℹ️ Sampel kecil ({closed} closed) — win rate "
                f"{wr*100:.0f}% belum konklusif")
    if wr < win_threshold:
        return "🚨 Win rate rendah — audit setup"
    return f"✅ Win rate sehat ({wr*100:.0f}%)"


if __name__ == "__main__":
    # Demo cepat dengan data IATA (EOD 2026-06-23)
    fib = {"R 0.786": 70, "R 0.618": 66, "R 0.500": 63,
           "R 0.382": 60, "R 0.236": 57, "Support": 51}
    print("FIB LADDER (fixed):")
    print(render_fib_ladder(fib, price=69))
    print(fib_position_note(fib, 69))
    print()
    print("ORDERBOOK 17369/17980 :", orderbook_label(17369, 17980))
    print("TREND 69/66/70        :", classify_trend(69, 66, 70))
    print("VALUE 94.9M lot @69    : Rp", f"{compute_value(94_943_200, 69):,.0f}")
    print("WEEKLY winrate 0/0     :", format_winrate(0, 0),
          "|", weekly_insight(0, 0))
