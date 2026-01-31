# app.py

import io
import os
import json
from datetime import datetime
from typing import Optional, Dict, List

import streamlit as st

from src.parser import parse_html_to_A_to_K


# =========================
# Helpers
# =========================
def idr_to_int(s: str) -> int:
    """'IDR 1.200.000' / '1,200,000' / '1200000' -> 1200000"""
    if s is None:
        return 0
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    return int(digits) if digits else 0


def fmt_idr(n: int) -> str:
    """Format 'IDR 1.234.567' (titik = pemisah ribuan)."""
    s = f"{n:,}".replace(",", ".")
    return f"IDR {s}"


def ensure_states():
    """Inisialisasi session_state."""
    if "parsed_AK" not in st.session_state:
        st.session_state.parsed_AK: Dict[str, Optional[str]] = {}
    if "reimburse_rows" not in st.session_state:
        st.session_state.reimburse_rows: List[Dict] = []
    if "totals_LQ" not in st.session_state:
        st.session_state.totals_LQ: Dict[str, int] = {k: 0 for k in list("LMNOPQ")}
    if "bg_template_bytes" not in st.session_state:
        st.session_state.bg_template_bytes: Optional[bytes] = None
    if "tune_dict" not in st.session_state:
        st.session_state.tune_dict = None


def recompute_totals():
    """Hitung L..Q dari daftar reimburse_rows."""
    kind_to_letter = {
        "bensin": "L",
        "hotel": "M",
        "toll": "N",
        "transportasi": "O",
        "parkir": "P",
    }
    totals = {k: 0 for k in kind_to_letter.keys()}

    for row in st.session_state.reimburse_rows:
        jenis = row["jenis"]
        totals[jenis] += int(row["nominal"])

    LQ = {letter: totals[jenis] for jenis, letter in {
        "bensin": "L",
        "hotel": "M",
        "toll": "N",
        "transportasi": "O",
        "parkir": "P",
    }.items()}
    LQ["Q"] = sum(LQ.values())
    st.session_state.totals_LQ = LQ


def parse_date_or_none(s: Optional[str]) -> Optional[datetime]:
    """Parse tanggal umum EN ke datetime; gagal -> None."""
    if not s:
        return None
    for fmt in ("%d %B, %Y", "%d %b, %Y", "%d %B %Y", "%d %b %Y", "%d/%B/%Y", "%d/%b/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def inclusive_days(d1: Optional[datetime], d2: Optional[datetime]) -> Optional[int]:
    """Selisih hari inklusif (mis. 19–21 = 3)."""
    if not d1 or not d2:
        return None
    return (d2.date() - d1.date()).days + 1


# =========================
# PDF Builder (Overlay 1:1)
# =========================
def build_spj_pdf_overlay(
    AK: Dict[str, Optional[str]],
    LQ: Dict[str, int],
    overlay_template_bytes: Optional[bytes],
    tune: Optional[Dict[str, Dict[str, float]]] = None,
) -> bytes:
    """
    Overlay nilai A–Q tepat di atas template kosong (1 halaman).
    - Koordinat sudah disetel agar 'jatuh' 1:1 pada template.
    - 'tune' = penggeser halus (pt) untuk global & per-bagian bila perlu.
    """
    # Lazy import agar UI tidak crash bila dependency belum terpasang
    try:
        from reportlab.pdfgen import canvas
    except Exception as e:
        st.error("`reportlab` belum terpasang. Tambahkan ke requirements.txt. Detail: " + str(e))
        return b""
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except Exception as e:
        st.error("`PyPDF2` belum terpasang. Tambahkan ke requirements.txt. Detail: " + str(e))
        return b""

    # ---------- Nilai A–Q ----------
    def _s(x: Optional[str]) -> str:
        return (x or "").strip()

    A = _s(AK.get("A"))
    B = _s(AK.get("B"))
    C = _s(AK.get("C"))
    D = _s(AK.get("D"))
    E = _s(AK.get("E"))
    G = _s(AK.get("G"))
    H = _s(AK.get("H"))
    I = _s(AK.get("I"))
    K_txt = _s(AK.get("K") or "IDR 0")

    def _idr_to_int(s: str) -> int:
        digits = "".join(ch for ch in str(s) if ch.isdigit())
        return int(digits) if digits else 0

    K_val = _idr_to_int(K_txt)
    L_val = int(LQ.get("L", 0))
    M_val = int(LQ.get("M", 0))
    N_val = int(LQ.get("N", 0))
    O_val = int(LQ.get("O", 0))
    P_val = int(LQ.get("P", 0))
    Q_val = int(LQ.get("Q", 0))

    d_dt = parse_date_or_none(D)
    e_dt = parse_date_or_none(E)
    hari_str = str(inclusive_days(d_dt, e_dt) or "")  # jumlah hari (inklusif)

    def fmt_n(n: int) -> str:
        return f"{n:,}".replace(",", ".")

    # ---------- Template wajib ----------
    if not overlay_template_bytes:
        st.error("Template background belum tersedia. Taruh di assets/spj_blank.pdf atau upload di UI.")
        return b""

    base_reader = PdfReader(io.BytesIO(overlay_template_bytes))
    base_page = base_reader.pages[0]
    PAGE_W = float(base_page.mediabox.width)
    PAGE_H = float(base_page.mediabox.height)

    # ---------- Offset kalibrasi ----------
    tune = tune or {}
    def _off(section: str) -> tuple[float, float]:
        g = tune.get("global", {})
        s = tune.get(section, {})
        return float(g.get("dx", 0.0) + s.get("dx", 0.0)), float(g.get("dy", 0.0) + s.get("dy", 0.0))

    # ---------- Canvas overlay ----------
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(PAGE_W, PAGE_H))

    def draw_text(x, y, text, size=10, bold=False, align="left"):
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        if align == "left":
            c.drawString(x, y, text)
        elif align == "center":
            c.drawCentredString(x, y, text)
        elif align == "right":
            c.drawRightString(x, y, text)

    # ========== KOORDINAT 1:1 (disesuaikan untuk template kosong) ==========
    # Catatan:
    # - Satuan point; (0,0) = kiri-bawah.
    # - Jarak antar baris ~18 pt untuk blok-bok bernomor.
    # - Kolom angka kanan dibuat align="right" agar digit rata kanan.

    # ---- IDENTITAS (nilai setelah titik-dua) ----
    dx, dy = _off("ident")
    XVAL_IDENT = 228  # kolom nilai identitas setelah ':'
    draw_text(XVAL_IDENT + dx, PAGE_H - 136 + dy, A, size=10)      # ATAS NAMA  (*A)
    draw_text(XVAL_IDENT + dx, PAGE_H - 154 + dy, B, size=10)      # TEMPAT ASAL (*B)
    draw_text(XVAL_IDENT + dx, PAGE_H - 172 + dy, C, size=10)      # TUJUAN      (*C)
    draw_text(XVAL_IDENT + dx, PAGE_H - 190 + dy, D, size=10)      # TGL BERANGKAT (*D)
    draw_text(XVAL_IDENT + dx, PAGE_H - 208 + dy, E, size=10)      # TGL KEMBALI   (*E)
    draw_text(XVAL_IDENT + dx, PAGE_H - 226 + dy, hari_str, size=10)  # JUMLAH HARI

    # ---- A. REALISASI BIAYA HARIAN ----
    dx, dy = _off("A")
    draw_text(145 + dx, PAGE_H - 320 + dy, fmt_n(K_val), size=10)     # Rp. <K>
    draw_text(245 + dx, PAGE_H - 320 + dy, "REALISASI HARI", size=10)
    draw_text(92  + dx, PAGE_H - 338 + dy, hari_str, size=10)         # <hari>
    draw_text(112 + dx, PAGE_H - 338 + dy, "Hari", size=10)
    draw_text(40  + dx, PAGE_H - 356 + dy, "SELISIH KURANG (kembali ke karyawan)", size=10)
    draw_text(145 + dx, PAGE_H - 374 + dy, fmt_n(K_val), size=10)     # <K>
    draw_text(220 + dx, PAGE_H - 374 + dy, "(AKOMODASI DITANGGUNG PANITIA)", size=10)
    draw_text(40  + dx, PAGE_H - 392 + dy, "SELISIH TAMBAH (kembali ke perusahaan)", size=10)
    draw_text(145 + dx, PAGE_H - 410 + dy, "-", size=10)

    # ---- B. FASILITAS TRANSPORTASI (PESAWAT) ----
    dx, dy = _off("B")
    draw_text(145 + dx, PAGE_H - 444 + dy, "Rp.", size=10)
    draw_text(40  + dx, PAGE_H - 462 + dy, "REALISASI", size=10)
    draw_text(145 + dx, PAGE_H - 480 + dy, "-", size=10)
    draw_text(40  + dx, PAGE_H - 498 + dy, "SELISIH KURANG (kembali ke karyawan)", size=10)
    draw_text(145 + dx, PAGE_H - 516 + dy, "-", size=10)
    draw_text(40  + dx, PAGE_H - 534 + dy, "SELISIH TAMBAH (kembali ke perusahaan)", size=10)
    draw_text(145 + dx, PAGE_H - 552 + dy, "-", size=10)

    # ---- C. REALISASI BIAYA PENGINAPAN ----
    dx, dy = _off("C")
    draw_text(145 + dx, PAGE_H - 586 + dy, "Rp.", size=10)
    draw_text(40  + dx, PAGE_H - 604 + dy, "REALISASI", size=10)
    draw_text(145 + dx, PAGE_H - 622 + dy, "-", size=10)
    draw_text(178 + dx, PAGE_H - 622 + dy, "(CTM)", size=10)
    draw_text(40  + dx, PAGE_H - 640 + dy, "SELISIH KURANG (kembali ke karyawan)", size=10)
    draw_text(145 + dx, PAGE_H - 658 + dy, "-", size=10)
    draw_text(40  + dx, PAGE_H - 676 + dy, "SELISIH TAMBAH (kembali ke perusahaan)", size=10)
    draw_text(145 + dx, PAGE_H - 694 + dy, "-", size=10)

    # ---- D. JENIS BIAYA LAIN-LAIN ----
    dx, dy = _off("D")
    XNUM_R = 325  # kolom angka kanan (rata kanan)
    draw_text(XNUM_R + dx, PAGE_H - 728 + dy, fmt_n(L_val), size=10, align="right")  # *L bensin
    draw_text(XNUM_R + dx, PAGE_H - 746 + dy, fmt_n(M_val), size=10, align="right")  # *M hotel
    draw_text(XNUM_R + dx, PAGE_H - 764 + dy, fmt_n(N_val), size=10, align="right")  # *N toll
    draw_text(XNUM_R + dx, PAGE_H - 782 + dy, fmt_n(O_val), size=10, align="right")  # *O transportasi
    draw_text(XNUM_R + dx, PAGE_H - 800 + dy, fmt_n(P_val), size=10, align="right")  # *P parkir
    draw_text(40      + dx, PAGE_H - 818 + dy, fmt_n(Q_val), size=10)                # *Q selisih kurang total

    # ---- RINGKASAN (I / II / TOTAL) ----
    dx, dy = _off("SUM")
    draw_text(120 + dx, PAGE_H - 848 + dy, fmt_n(Q_val), size=10, bold=True)  # I. TOTAL SELISIH KURANG
    draw_text(120 + dx, PAGE_H - 880 + dy, "-",          size=10, bold=True)  # II. TOTAL SELISIH TAMBAH
    draw_text(120 + dx, PAGE_H - 912 + dy, fmt_n(Q_val), size=10, bold=True)  # TOTAL SELISIH

    # ---- Mengetahui / TTD ----
    dx, dy = _off("TTD")
    draw_text(40  + dx, PAGE_H - 948 + dy, (H if H else I), size=10, bold=True)  # kiri: pejabat
    draw_text(300 + dx, PAGE_H - 948 + dy, A,             size=10, bold=True)    # kanan: pelaksana
    draw_text(40  + dx, PAGE_H - 972 + dy, D, size=10)                            # tanggal berangkat
    draw_text(180 + dx, PAGE_H - 972 + dy, E, size=10)                            # tanggal kembali
    if G:
        draw_text(40 + dx, PAGE_H - 990 + dy, G, size=10)                         # jabatan (opsional)

    # Selesai overlay
    c.showPage()
    c.save()
    overlay_pdf = packet.getvalue()

    # Merge ke template
    try:
        overlay_reader = PdfReader(io.BytesIO(overlay_pdf))
        overlay_page = overlay_reader.pages[0]
        base_page.merge_page(overlay_page)
        writer = PdfWriter()
        writer.add_page(base_page)
        out_buf = io.BytesIO()
        writer.write(out_buf)
        return out_buf.getvalue()
    except Exception as e:
        st.warning(f"Gagal overlay; mengembalikan overlay saja. Detail: {e}")
        return overlay_pdf


# =========================
# UI
# =========================
st.set_page_config(page_title="Trip HTML Parser (A–Q) + SPJ PDF (Overlay)", page_icon="🧭", layout="wide")
ensure_states()

st.title("🧭 Trip HTML Parser (A–Q) + SPJ PDF (Overlay)")
st.caption("Tempel/unggah HTML → A–K → Reimburse (L–Q) → Unduh PDF di atas template kosong")

with st.expander("Cara pakai", expanded=False):
    st.markdown("""
    1) Tempel/unggah HTML Trip Detail, klik **Parse HTML** → dapatkan A–K.  
    2) Isi **Reimburse** (bensin/hotel/toll/transportasi/parkir) → L–Q.  
    3) Siapkan **template kosong** sebagai background:
       - Letakkan file di repo: `assets/spj_blank.pdf`, atau
       - Unggah melalui komponen uploader di bawah.  
    4) (Opsional) Sesuaikan **kalibrasi offset** bila perlu → Unduh **PDF SPJ (Overlay)**.
    """)

# ========== Input HTML ==========
tab1, tab2 = st.tabs(["📄 Tempel HTML", "📤 Unggah HTML"])
html_text = ""

with tab1:
    html_text_input = st.text_area(
        "Tempel HTML di sini",
        height=420,
        placeholder="Tempel HTML lengkap Trip Detail...",
    )
    if html_text_input:
        html_text = html_text_input

with tab2:
    uploaded = st.file_uploader("Unggah file HTML", type=["html", "htm"])
    if uploaded:
        html_text = uploaded.read().decode("utf-8", errors="ignore")

parse_btn = st.button("🔎 Parse HTML", type="primary", use_container_width=True)

# ========== Parse A–K ==========
if parse_btn:
    if not html_text.strip():
        st.error("HTML kosong.")
    else:
        st.session_state.parsed_AK = parse_html_to_A_to_K(html_text)

# Tampilkan A–K
if st.session_state.parsed_AK:
    st.subheader("📌 Hasil Ekstraksi A–K")
    AtoK = st.session_state.parsed_AK

    col1, col2 = st.columns(2)
    with col1:
        st.write("**A – Employee Name:**", AtoK.get("A"))
        st.write("**B – Trip From:**", AtoK.get("B"))
        st.write("**C – Trip To:**", AtoK.get("C"))
        st.write("**D – Depart Date:**", AtoK.get("D"))
        st.write("**E – Return Date:**", AtoK.get("E"))
    with col2:
        st.write("**F – Purpose:**", AtoK.get("F"))
        st.write("**G – Position:**", AtoK.get("G"))
        st.write("**H – Timeline Role:**", AtoK.get("H"))
        st.write("**I – Timeline By:**", AtoK.get("I"))
        st.write("**J – Daily Allowance (Days):**", AtoK.get("J"))
        st.write("**K – Daily Allowance Total:**", AtoK.get("K"))

    st.divider()

# ========== Reimburse L–Q ==========
st.subheader("🧾 Reimburse (L–Q)")

with st.form("form_reimburse", clear_on_submit=True):
    jenis = st.selectbox(
        "Jenis biaya",
        ["bensin", "hotel", "toll", "transportasi", "parkir"]
    )
    nominal = st.text_input("Nominal (contoh: 1200000 atau IDR 1.200.000)")
    submit = st.form_submit_button("Tambah", use_container_width=True)

    if submit:
        nilai = idr_to_int(nominal)
        if nilai <= 0:
            st.warning("Nominal harus lebih dari 0.")
        else:
            st.session_state.reimburse_rows.append({
                "jenis": jenis,
                "nominal": nilai
            })
            recompute_totals()
            st.success("Berhasil ditambahkan!")

# Tabel Reimburse
st.markdown("### 📋 Tabel Reimburse")
rows = st.session_state.reimburse_rows
if not rows:
    st.info("Belum ada data reimburse.")
else:
    header = st.columns([0.7, 3, 3, 2])
    header[0].write("**No**")
    header[1].write("**Jenis**")
    header[2].write("**Nominal**")
    header[3].write("**Aksi**")

    for idx, row in enumerate(rows, start=1):
        c1, c2, c3, c4 = st.columns([0.7, 3, 3, 2])
        c1.write(idx)
        c2.write(row["jenis"].capitalize())
        c3.write(fmt_idr(row["nominal"]))
        if c4.button("Hapus", key=f"hapus_{idx}"):
            del st.session_state.reimburse_rows[idx - 1]
            recompute_totals()
            try:
                st.rerun()
            except Exception:
                st.experimental_rerun()

# Total L–Q
recompute_totals()
totals = st.session_state.totals_LQ

st.subheader("📌 Total L–Q")
cols = st.columns(6)
cols[0].metric("L – Bensin", fmt_idr(totals["L"]))
cols[1].metric("M – Hotel", fmt_idr(totals["M"]))
cols[2].metric("N – Toll", fmt_idr(totals["N"]))
cols[3].metric("O – Transportasi", fmt_idr(totals["O"]))
cols[4].metric("P – Parkir", fmt_idr(totals["P"]))
cols[5].metric("Q – Total Semua", fmt_idr(totals["Q"]))

# JSON A–Q
combined = {
    **st.session_state.parsed_AK,
    **{k: totals[k] for k in "LMNOPQ"},
}
st.divider()
st.subheader("💾 Unduh JSON (A–Q)")
json_str = json.dumps(combined, ensure_ascii=False, indent=2)
st.code(json_str, language="json")
st.download_button(
    "Download JSON",
    json_str,
    file_name="trip_A_to_Q.json",
    mime="application/json",
    use_container_width=True,
)

# ========== Template background ==========
st.divider()
st.subheader("🧩 Template Background")

DEFAULT_BG_PATH = os.environ.get("SPJ_BG_PATH", "assets/spj_blank.pdf")
if not st.session_state.bg_template_bytes:
    try:
        if os.path.exists(DEFAULT_BG_PATH):
            with open(DEFAULT_BG_PATH, "rb") as f:
                st.session_state.bg_template_bytes = f.read()
            st.info(f"Template background di-load dari: {DEFAULT_BG_PATH}")
    except Exception as e:
        st.warning(f"Tidak bisa membaca {DEFAULT_BG_PATH}: {e}")

bg_file = st.file_uploader("Atau unggah template PDF kosong", type=["pdf"], key="bg_tpl")
if bg_file is not None:
    st.session_state.bg_template_bytes = bg_file.read()
    st.success("Template background berhasil dimuat dari upload.")

# ===== Kalibrasi posisi (opsional) =====
st.subheader("🎯 Kalibrasi posisi (opsional)")
with st.expander("Buka kalibrasi", expanded=False):
    st.caption("Satuan = point (pt). 1 pt ≈ 0.3528 mm. Mulai dari offset kecil: 1–3 pt.")

    colg1, colg2 = st.columns(2)
    with colg1:
        g_dx = st.number_input("Global dx (+kanan / −kiri)", value=0.0, step=1.0, key="cal_g_dx")
        a_dx = st.number_input("A (Harian) dx", value=0.0, step=1.0, key="cal_A_dx")
        b_dx = st.number_input("B (Pesawat) dx", value=0.0, step=1.0, key="cal_B_dx")
        c_dx = st.number_input("C (Penginapan) dx", value=0.0, step=1.0, key="cal_C_dx")
        d_dx = st.number_input("D (Lain-lain) dx", value=0.0, step=1.0, key="cal_D_dx")
    with colg2:
        g_dy = st.number_input("Global dy (+atas / −bawah)", value=0.0, step=1.0, key="cal_g_dy")
        a_dy = st.number_input("A (Harian) dy", value=0.0, step=1.0, key="cal_A_dy")
        b_dy = st.number_input("B (Pesawat) dy", value=0.0, step=1.0, key="cal_B_dy")
        c_dy = st.number_input("C (Penginapan) dy", value=0.0, step=1.0, key="cal_C_dy")
        d_dy = st.number_input("D (Lain-lain) dy", value=0.0, step=1.0, key="cal_D_dy")

    colb1, colb2 = st.columns(2)
    with colb1:
        ident_dx = st.number_input("Identitas dx", value=0.0, step=1.0, key="cal_ident_dx")
        sum_dx   = st.number_input("Ringkasan (I/II/TOTAL) dx", value=0.0, step=1.0, key="cal_SUM_dx")
        ttd_dx   = st.number_input("TTD dx", value=0.0, step=1.0, key="cal_TTD_dx")
    with colb2:
        ident_dy = st.number_input("Identitas dy", value=0.0, step=1.0, key="cal_ident_dy")
        sum_dy   = st.number_input("Ringkasan (I/II/TOTAL) dy", value=0.0, step=1.0, key="cal_SUM_dy")
        ttd_dy   = st.number_input("TTD dy", value=0.0, step=1.0, key="cal_TTD_dy")

    st.caption("Tip: coba mulai Global dy = +2 atau −2. Jika semua naik/turun bersama, berarti offset global sudah tepat.")

    st.session_state["tune_dict"] = {
        "global": {"dx": g_dx, "dy": g_dy},
        "ident":  {"dx": ident_dx, "dy": ident_dy},
        "A":      {"dx": a_dx, "dy": a_dy},
        "B":      {"dx": b_dx, "dy": b_dy},
        "C":      {"dx": c_dx, "dy": c_dy},
        "D":      {"dx": d_dx, "dy": d_dy},
        "SUM":    {"dx": sum_dx, "dy": sum_dy},
        "TTD":    {"dx": ttd_dx, "dy": ttd_dy},
    }

# ========== Export PDF (Overlay) ==========
st.subheader("📄 Export PDF — SPJ (overlay di atas template)")
if st.button("🧾 Unduh PDF SPJ (Overlay)", use_container_width=True):
    if not st.session_state.parsed_AK:
        st.warning("Data A–K belum ada. Silakan parse HTML terlebih dahulu.")
    elif not st.session_state.bg_template_bytes:
        st.warning("Template background belum tersedia. Upload file atau letakkan di assets/spj_blank.pdf.")
    else:
        tune = st.session_state.get("tune_dict", None)
        pdf_bytes = build_spj_pdf_overlay(
            st.session_state.parsed_AK,
            totals,
            st.session_state.bg_template_bytes,
            tune=tune
        )
        if pdf_bytes:
            st.download_button(
                "⬇️ Klik untuk mengunduh PDF SPJ (Overlay)",
                pdf_bytes,
                file_name="SPJ_Realisasi_Perjalanan_Dinas_overlay.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
