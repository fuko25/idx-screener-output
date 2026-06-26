# BRIEF KERJA — repo idx-bandarmologi (paste di sesi baru repo ini)

Halo Claude. Aku kerja di repo bot screener `idx-bandarmologi`. Tolong kerjakan
tugas berikut **berurutan**, dan **selalu lakukan sendiri: edit → commit → push**.
Buat branch kerja baru, jangan langsung ke main.

================================================================
TUGAS A — JADIKAN INVEZGO SATU-SATUNYA SUMBER DATA (prioritas utama)
================================================================
Sekarang bot menarik data dari sumber campuran. Ganti SEMUA pengambilan data
jadi dari Invezgo saja.

Langkah:
1. Audit dulu: `grep -rniE "requests|http|api|fetch|scrape|source|url" --include=*.py .`
   → petakan SEMUA tempat data masuk (harga, volume, broker summary, foreign
   flow, orderbook, dll) dan dari mana asalnya sekarang.
2. Laporkan ke aku peta sumber data lama SEBELUM mengganti (biar aku tahu apa
   yang dibuang).
3. Ganti semua sumber itu ke Invezgo:
   - Base URL: https://mcp.invezgo.com  (MCP) / API Invezgo (schema sama).
   - Auth: pakai API key dari ENV (mis. INVEZGO_API_KEY), JANGAN hardcode.
   - Invezgo auto-detect schema; pakai key yang sama untuk API & MCP.
4. Bikin satu modul adapter (mis. `data/invezgo.py`) sebagai SATU pintu data,
   semua fungsi lain ambil dari situ. Hapus/route-out sumber lama.
5. Pastikan field yang dipakai analisa tetap kebaca: harga, %change, bid/offer,
   volume (lot), freq, broker buy/sell 1D, foreign flow 1D/7D/30D, EMA/RSI/ATR.

================================================================
TUGAS B — VERIFIKASI API KEY INVEZGO BARU
================================================================
1. `grep -rniE "invezgo|api_key|apikey|token" .` → temukan SEMUA tempat key
   dipakai/dibaca. Pastikan semua baca dari ENV yang sama, tidak ada key lama
   nyangkut/hardcoded.
2. Cek GitHub Actions: `.github/workflows/*.yml` → pastikan env `INVEZGO_API_KEY`
   diisi dari `secrets.INVEZGO_API_KEY`.
3. Jalankan smoke test kecil (panggil 1 endpoint Invezgo pakai key dari ENV) →
   konfirmasi balikannya data, bukan 401/unauthorized. Laporkan hasilnya.

================================================================
TUGAS C — PERBAIKI 11 BUG FORMAT ANALISA + WEEKLY REPORT
================================================================
Acuan implementasi sudah ditulis di repo `idx-screener-output` →
file `fixes/report_fixes.py` (ambil/lihat sebagai referensi). Terapkan:

1.  Verdict/insight kepotong di tengah kalimat → potong di batas kalimat
    (clip_insight), naikkan limit.
2.  Fib ladder salah posisi "Harga NOW" → sisipkan baris harga lalu SORT desc
    by nilai (render_fib_ladder). Muncul di SEMUA sampel (GJTL/TSPC/IATA/DEWI).
3.  Satuan volume "lot" vs "shares": Nilai transaksi meleset 100x. Tetapkan satu
    satuan (lot), Nilai = lot×100×harga (compute_value, LOT_SIZE=100).
4.  VA20 ratio implausibel (50–240x) → akibat mismatch satuan #3; pastikan
    pembanding sama-sama lot (compute_va20_ratio).
5.  Orderbook label "lemah" padahal ~1.0x → pakai nilai asli utk threshold,
    0.8–1.5 = "seimbang", tampil 2 desimal (orderbook_label).
6.  Trend salah: EMA20<EMA50 dilabeli UPTREND (IATA, DEWI) → klasifikasi trend
    dari relasi EMA + posisi harga (classify_trend), bukan default.
7.  RSI tepat 50.0 saat data kurang → jangan fallback diam-diam; tandai
    "n/a (data <14H)" (safe_rsi).
8.  Verbosity by verdict: REJECT → one-liner; NEUTRAL → ringkas; APPROVE →
    full detail (render_analysis). Detail REJECT cukup disimpan ke export JSON.
9.  Weekly report win-rate 0/0 → JANGAN 0.0%. closed==0 → tampil "N/A" &
    insight "belum ada posisi closed"; "🚨 audit setup" hanya jika
    closed>=MIN_SAMPLE & win_rate<threshold (weekly_winrate/weekly_insight).
10. **Market tutup / data belum tersedia DIBACA "volume nol / tidak likuid" →
    REJECT palsu** (kasus DEWI: naik +1.68% tapi di-REJECT "tidak likuid").
    Tambah guard: kalau data intraday belum tersedia → TUNDA analisa
    ("⏸️ Data belum tersedia, analisa ditunda"), JANGAN jalankan verdict.
11. Saat data kosong, orderbook (0/0) & bandar/retail render default
    ("0.0x lemah", "Retail 100%"). Harus "n/a — data tidak tersedia", dan
    jangan diumpankan ke verdict.

================================================================
ATURAN
================================================================
- Kerjakan A → B → C berurutan. Lapor temuan tiap tahap sebelum perubahan besar.
- Branch kerja baru; commit kecil-kecil dgn pesan jelas; push sendiri.
- Jangan hardcode secret. Jangan buat PR kecuali aku minta.
