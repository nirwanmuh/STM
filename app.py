# app.py

import io
import os
import json
import base64
from datetime import datetime
from typing import Optional, Dict, List

import streamlit as st
import streamlit.components.v1 as components

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
    if "tune_value" not in st.session_state:
        # Struktur kalibrasi per-value (dx/dy) + global
        st.session_state.tune_value = {
            "GLOBAL": {"dx": 0.0, "dy": 0.0},
            # Identitas:
            "A": {"dx": 0.0, "dy": 0.0},   # ATAS NAMA
            "B": {"dx": 0.0, "dy": 0.0},   # TEMPAT ASAL
            "C": {"dx": 0.0, "dy": 0.0},   # TUJUAN
            "D": {"dx": 0.0, "dy": 0.0},   # TGL BERANGKAT (identitas)
            "E": {"dx": 0.0, "dy": 0.0},   # TGL KEMBALI (identitas)
            "DAYS": {"dx": 0.0, "dy": 0.0},  # JUMLAH HARI (identitas)
            # A. Harian:
            "K": {"dx": 0.0, "dy": 0.0},      # nilai K (baris REALISASI HARI)
            "A_DAYS": {"dx": 0.0, "dy": 0.0}, # jumlah hari di blok A
            "K_DIFF": {"dx": 0.0, "dy": 0.0}, # K untuk SELISIH KURANG (blok A)
            # D. Lain-lain:
            "L": {"dx": 0.0, "dy": 0.0},
            "M": {"dx": 0.0, "dy": 0.0},
            "N": {"dx": 0.0, "dy": 0.0},
            "O": {"dx": 0.0, "dy": 0.0},
            "P": {"dx": 0.0, "dy": 0.0},
            "Q": {"dx": 0.0, "dy": 0.0},    # selisih kurang total (kiri bawah D)
            # Ringkasan:
            "SUM_Q1": {"dx": 0.0, "dy": 0.0},   # I. TOTAL SELISIH KURANG (Q)
            "SUM_QTOT": {"dx": 0.0, "dy": 0.0}, # TOTAL SELISIH (Q)
            # TTD/Footer:
            "H": {"dx": 0.0, "dy": 0.0},        # nama pejabat kiri (H) – jika kosong pakai I
            "I": {"dx": 0.0, "dy": 0.0},        # nama alternatif kiri (I)
            "A_SIGN": {"dx": 0.0, "dy": 0.0},   # nama pelaksana kanan (A)
            "DATE_D": {"dx": 0.0, "dy": 0.0},   # tanggal (D) di footer
            "DATE_E": {"dx": 0.0, "dy": 0.0},   # tanggal (E) di footer
            "G": {"dx": 0.0, "dy": 0.0},        # jabatan (opsional) di footer
        }
    if "preview_pdf_bytes" not in st.session_state:
        st.session_state.preview_pdf_bytes: Optional[bytes] = None
    if "auto_preview" not in st.session_state:
        st.session_state.auto_preview = False


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
# PDF Builder (Overlay 1:1; per-value calibration)
# =========================
def build_spj_pdf_overlay(
    AK: Dict[str, Optional[str]],
    LQ: Dict[str, int],
    overlay_template_bytes: Optional[bytes],
    tune_value: Dict[str, Dict[str, float]],
) -> bytes:
    """
    Overlay nilai A–Q di atas template kosong (1 halaman).
    - Hanya menulis NILAI (tanpa label) agar tidak duplikasi dengan label di template.
    - Koordinat dipatok 1:1; setiap value bisa di-offset (dx/dy) via 'tune_value'.
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
    days = inclusive_days(d_dt, e_dt) or 0
    hari_str = str(days)

    def fmt_n(n: int) -> str:
        # 3.840.000
        return f"{n:,}".replace(",", ".")

    # ---------- Template wajib ----------
    if not overlay_template_bytes:
        st.error("Template background belum tersedia. Taruh di assets/spj_blank.pdf atau upload di UI.")
        return b""

    base_reader = PdfReader(io.BytesIO(overlay_template_bytes))
    base_page = base_reader.pages[0]
    PAGE_W = float(base_page.mediabox.width)
    PAGE_H = float(base_page.mediabox.height)

    # ---------- Offset per-value ----------
    tv = tune_value or {}
    gdx = float(tv.get("GLOBAL", {}).get("dx", 0.0))
    gdy = float(tv.get("GLOBAL", {}).get("dy", 0.0))

    def _v(key: str) -> tuple[float, float]:
        dx = float(tv.get(key, {}).get("dx", 0.0))
        dy = float(tv.get(key, {}).get("dy", 0.0))
        return gdx + dx, gdy + dy

    # ---------- Canvas overlay ----------
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(PAGE_W, PAGE_H))

    def draw_text(x, y, text, size=10, bold=False, align="left"):
        if text is None or text == "":
            return
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        if align == "left":
            c.drawString(x, y, text)
        elif align == "center":
            c.drawCentredString(x, y, text)
        elif align == "right":
            c.drawRightString(x, y, text)

    # ========== KOORDINAT DASAR (nilai saja, tanpa label) ==========
    # — IDENTITAS —
    XVAL_IDENT = 228
    dx, dy = _v("A");     draw_text(XVAL_IDENT + dx, PAGE_H - 136 + dy, A, size=10)        # ATAS NAMA
    dx, dy = _v("B");     draw_text(XVAL_IDENT + dx, PAGE_H - 154 + dy, B, size=10)        # TEMPAT ASAL
    dx, dy = _v("C");     draw_text(XVAL_IDENT + dx, PAGE_H - 172 + dy, C, size=10)        # TUJUAN
    dx, dy = _v("D");     draw_text(XVAL_IDENT + dx, PAGE_H - 190 + dy, D, size=10)        # TGL BERANGKAT
    dx, dy = _v("E");     draw_text(XVAL_IDENT + dx, PAGE_H - 208 + dy, E, size=10)        # TGL KEMBALI
    dx, dy = _v("DAYS");  draw_text(XVAL_IDENT + dx, PAGE_H - 226 + dy, hari_str, size=10) # JUMLAH HARI

    # — A. HARIAN —
    dx, dy = _v("K");       draw_text(145 + dx, PAGE_H - 320 + dy, fmt_n(K_val), size=10)   # K (Realisasi Harian)
    dx, dy = _v("A_DAYS");  draw_text(92  + dx, PAGE_H - 338 + dy, hari_str, size=10)       # Hari (blok A)
    dx, dy = _v("K_DIFF");  draw_text(145 + dx, PAGE_H - 374 + dy, fmt_n(K_val), size=10)   # K (Selisih Kurang)

    # — D. LAIN-LAIN (kolom angka kanan rata-kanan) —
    XNUM_R = 330
    if L_val: dx, dy = _v("L"); draw_text(XNUM_R + dx, PAGE_H - 728 + dy, fmt_n(L_val), size=10, align="right")
    if M_val: dx, dy = _v("M"); draw_text(XNUM_R + dx, PAGE_H - 746 + dy, fmt_n(M_val), size=10, align="right")
    if N_val: dx, dy = _v("N"); draw_text(XNUM_R + dx, PAGE_H - 764 + dy, fmt_n(N_val), size=10, align="right")
    if O_val: dx, dy = _v("O"); draw_text(XNUM_R + dx, PAGE_H - 782 + dy, fmt_n(O_val), size=10, align="right")
    if P_val: dx, dy = _v("P"); draw_text(XNUM_R + dx, PAGE_H - 800 + dy, fmt_n(P_val), size=10, align="right")
    if Q_val: dx, dy = _v("Q"); draw_text(40 + dx, PAGE_H - 818 + dy, fmt_n(Q_val), size=10)  # total D (kiri)

    # — RINGKASAN (I/II/TOTAL) —
    if Q_val:
        dx, dy = _v("SUM_Q1");  draw_text(120 + dx, PAGE_H - 848 + dy, fmt_n(Q_val), size=10, bold=True)  # I. TOTAL SELISIH KURANG
        dx, dy = _v("SUM_QTOT");draw_text(120 + dx, PAGE_H - 912 + dy, fmt_n(Q_val), size=10, bold=True)  # TOTAL SELISIH
    # II. TOTAL SELISIH TAMBAH = '-' → tidak ditulis

    # — Mengetahui / TTD —
    ttd_left_name = H if H else I
    dx, dy = _v("H" if H else "I"); draw_text(40 + dx,  PAGE_H - 948 + dy, ttd_left_name, size=10, bold=True)  # kiri
    dx, dy = _v("A_SIGN");         draw_text(300 + dx, PAGE_H - 948 + dy, A,              size=10, bold=True)  # kanan
    dx, dy = _v("DATE_D");         draw_text(40 + dx,  PAGE_H - 972 + dy, D, size=10)                        # tanggal mulai
    dx, dy = _v("DATE_E");         draw_text(180 + dx, PAGE_H - 972 + dy, E, size=10)                        # tanggal akhir
    if G:
        dx, dy = _v("G");          draw_text(40 + dx, PAGE_H - 990 + dy, G, size=10)                         # jabatan (opsional)

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
st.caption("Tempel/unggah HTML → A–K → Reimburse (L–Q) → Live View + Unduh PDF di atas template kosong (kalibrasi per–value)")

with st.expander("Cara pakai", expanded=False):
    st.markdown("""
    1) Tempel/unggah HTML Trip Detail, klik **Parse HTML** → dapatkan A–K.  
    2) Isi **Reimburse** (bensin/hotel/toll/transportasi/parkir) → L–Q.  
    3) Siapkan **template kosong** sebagai background:
       - Letakkan file di repo: `assets/spj_blank.pdf`, atau
       - Unggah melalui komponen uploader di bawah.  
    4) Gunakan **Kalibrasi per–value** bila perlu → klik **🔁 Refresh Live View** untuk melihat hasilnya langsung.  
    5) Jika sudah pas, klik **🧾 Unduh PDF SPJ (Overlay)**.
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

# ===== Kalibrasi per–value =====
st.subheader("🎯 Kalibrasi per–value")
with st.expander("Buka kalibrasi per–value", expanded=False):
    st.caption("Satuan = point (pt). 1 pt ≈ 0.3528 mm. Atur dx (+kanan/−kiri), dy (+atas/−bawah).")

    tv = st.session_state.tune_value

    # Global
    g1, g2 = st.columns(2)
    with g1:
        tv["GLOBAL"]["dx"] = st.number_input("GLOBAL dx", value=float(tv["GLOBAL"]["dx"]), step=1.0, key="val_G_dx")
    with g2:
        tv["GLOBAL"]["dy"] = st.number_input("GLOBAL dy", value=float(tv["GLOBAL"]["dy"]), step=1.0, key="val_G_dy")

    st.markdown("**Identitas**")
    keys_id = [("A", "A (Atas Nama)"), ("B", "B (Tempat Asal)"), ("C", "C (Tujuan)"),
               ("D", "D (Tgl Berangkat)"), ("E", "E (Tgl Kembali)"), ("DAYS", "Days (E−D)")]
    for key, label in keys_id:
        cdx, cdy = st.columns(2)
        with cdx:
            tv[key]["dx"] = st.number_input(f"{label} dx", value=float(tv[key]["dx"]), step=1.0, key=f"val_{key}_dx")
        with cdy:
            tv[key]["dy"] = st.number_input(f"{label} dy", value=float(tv[key]["dy"]), step=1.0, key=f"val_{key}_dy")

    st.markdown("**A. Harian**")
    a_keys = [("K", "K (Realisasi Harian)"), ("A_DAYS", "Hari (blok A)"), ("K_DIFF", "K (Selisih Kurang)")]
    for key, label in a_keys:
        cdx, cdy = st.columns(2)
        with cdx:
            tv[key]["dx"] = st.number_input(f"{label} dx", value=float(tv[key]["dx"]), step=1.0, key=f"val_{key}_dx")
        with cdy:
            tv[key]["dy"] = st.number_input(f"{label} dy", value=float(tv[key]["dy"]), step=1.0, key=f"val_{key}_dy")

    st.markdown("**D. Lain-lain (angka kanan)**")
    d_keys = [("L", "L (Bensin)"), ("M", "M (Hotel)"), ("N", "N (Toll)"), ("O", "O (Transportasi)"),
              ("P", "P (Parkir)"), ("Q", "Q (Total D; kiri bawah)")]
    for key, label in d_keys:
        cdx, cdy = st.columns(2)
        with cdx:
            tv[key]["dx"] = st.number_input(f"{label} dx", value=float(tv[key]["dx"]), step=1.0, key=f"val_{key}_dx")
        with cdy:
            tv[key]["dy"] = st.number_input(f"{label} dy", value=float(tv[key]["dy"]), step=1.0, key=f"val_{key}_dy")

    st.markdown("**Ringkasan (kanan)**")
    sum_keys = [("SUM_Q1", "I. TOTAL SELISIH KURANG (Q)"), ("SUM_QTOT", "TOTAL SELISIH (Q)")]
    for key, label in sum_keys:
        cdx, cdy = st.columns(2)
        with cdx:
            tv[key]["dx"] = st.number_input(f"{label} dx", value=float(tv[key]["dx"]), step=1.0, key=f"val_{key}_dx")
        with cdy:
            tv[key]["dy"] = st.number_input(f"{label} dy", value=float(tv[key]["dy"]), step=1.0, key=f"val_{key}_dy")

    st.markdown("**TTD & Footer**")
    ttd_keys = [("H", "Nama Pejabat Kiri (H)"), ("I", "Nama Pejabat Kiri (I; fallback)"), ("A_SIGN", "Nama Pelaksana Kanan (A)"),
                ("DATE_D", "Tanggal Footer (D)"), ("DATE_E", "Tanggal Footer (E)"), ("G", "Jabatan Footer (G)")]
    for key, label in ttd_keys:
        cdx, cdy = st.columns(2)
        with cdx:
            tv[key]["dx"] = st.number_input(f"{label} dx", value=float(tv[key]["dx"]), step=1.0, key=f"val_{key}_dx")
        with cdy:
            tv[key]["dy"] = st.number_input(f"{label} dy", value=float(tv[key]["dy"]), step=1.0, key=f"val_{key}_dy")

    # Auto-refresh preview
    st.session_state.auto_preview = st.checkbox("Auto-refresh preview saat mengubah offset", value=st.session_state.auto_preview)

# ========== 📺 Live View (Preview PDF) ==========
st.subheader("📺 Live View (Preview PDF)")
pcol1, pcol2 = st.columns([1, 1])

with pcol1:
    if st.button("🔁 Refresh Live View", use_container_width=True):
        if not st.session_state.parsed_AK:
            st.warning("Data A–K belum ada. Silakan parse HTML terlebih dahulu.")
        elif not st.session_state.bg_template_bytes:
            st.warning("Template background belum tersedia. Upload file atau letakkan di assets/spj_blank.pdf.")
        else:
            pdf_bytes = build_spj_pdf_overlay(
                st.session_state.parsed_AK,
                st.session_state.totals_LQ,
                st.session_state.bg_template_bytes,
                tune_value=st.session_state.tune_value,
            )
            st.session_state.preview_pdf_bytes = pdf_bytes

with pcol2:
    if st.button("🧹 Hapus Preview", use_container_width=True):
        st.session_state.preview_pdf_bytes = None

# Auto-refresh jika diaktifkan (dan data tersedia)
if st.session_state.auto_preview and st.session_state.parsed_AK and st.session_state.bg_template_bytes:
    pdf_bytes = build_spj_pdf_overlay(
        st.session_state.parsed_AK,
        st.session_state.totals_LQ,
        st.session_state.bg_template_bytes,
        tune_value=st.session_state.tune_value,
    )
    st.session_state.preview_pdf_bytes = pdf_bytes

# Tampilkan preview jika ada
if st.session_state.preview_pdf_bytes:
    b64 = base64.b64encode(st.session_state.preview_pdf_bytes).decode("utf-8")
    iframe_html = f'''
        <iframe
            src="data:application/pdf;base64,{b64}"
            width="100%"
            height="820"
            type="application/pdf"
        ></iframe>
    '''
    components.html(iframe_html, height=840, scrolling=True)
else:
    st.info("Preview belum tersedia. Klik **🔁 Refresh Live View** setelah mengatur kalibrasi.")

# ========== Export PDF (Overlay) ==========
st.divider()
st.subheader("📄 Export PDF — SPJ (overlay di atas template)")
if st.button("🧾 Unduh PDF SPJ (Overlay)", use_container_width=True):
    if not st.session_state.parsed_AK:
        st.warning("Data A–K belum ada. Silakan parse HTML terlebih dahulu.")
    elif not st.session_state.bg_template_bytes:
        st.warning("Template background belum tersedia. Upload file atau letakkan di assets/spj_blank.pdf.")
    else:
        pdf_bytes = build_spj_pdf_overlay(
            st.session_state.parsed_AK,
            st.session_state.totals_LQ,
            st.session_state.bg_template_bytes,
            tune_value=st.session_state.tune_value,
        )
          pdf_bytes,
                file_name="SPJ_Realisasi_Perjalanan_Dinas_overlay.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
