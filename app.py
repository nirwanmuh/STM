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
    if s is None:
        return 0
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    return int(digits) if digits else 0


def fmt_idr(n: int) -> str:
    s = f"{n:,}".replace(",", ".")
    return f"IDR {s}"


def ensure_states():
    if "parsed_AK" not in st.session_state:
        st.session_state.parsed_AK: Dict[str, Optional[str]] = {}
    if "reimburse_rows" not in st.session_state:
        st.session_state.reimburse_rows: List[Dict] = []
    if "totals_LQ" not in st.session_state:
        st.session_state.totals_LQ: Dict[str, int] = {k: 0 for k in list("LMNOPQ")}
    if "bg_template_bytes" not in st.session_state:
        st.session_state.bg_template_bytes: Optional[bytes] = None


def recompute_totals():
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
    if not s:
        return None
    for fmt in ("%d %B, %Y", "%d %b, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def inclusive_days(d1: Optional[datetime], d2: Optional[datetime]) -> Optional[int]:
    if not d1 or not d2:
        return None
    return (d2.date() - d1.date()).days + 1


# =========================
# PDF Builder (Exact Layout w/ Overlay)
# =========================
def build_spj_pdf_overlay(
    AK: Dict[str, Optional[str]],
    LQ: Dict[str, int],
    overlay_template_bytes: Optional[bytes],
) -> bytes:
    """
    Menggambar teks A–Q lalu menimpa ke background template PDF satu halaman.
    """
    # Lazy import agar tidak crash jika dependency belum terpasang
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
    except Exception as e:
        st.error(
            "Package `reportlab` belum terpasang. Tambahkan ke `requirements.txt` "
            "lalu deploy ulang. Detail: " + str(e)
        )
        return b""

    try:
        from PyPDF2 import PdfReader, PdfWriter
    except Exception as e:
        st.error(
            "Package `PyPDF2` belum terpasang. Tambahkan ke `requirements.txt` "
            "lalu deploy ulang. Detail: " + str(e)
        )
        return b""

    # Ambil nilai A–Q
    A = (AK.get("A") or "").strip()
    B = (AK.get("B") or "").strip()
    C = (AK.get("C") or "").strip()
    D = (AK.get("D") or "").strip()
    E = (AK.get("E") or "").strip()
    G = (AK.get("G") or "").strip()
    H = (AK.get("H") or "").strip()
    I = (AK.get("I") or "").strip()
    K_txt = (AK.get("K") or "IDR 0").strip()

    K_val = idr_to_int(K_txt)
    L_val = int(LQ.get("L", 0))
    M_val = int(LQ.get("M", 0))
    N_val = int(LQ.get("N", 0))
    O_val = int(LQ.get("O", 0))
    P_val = int(LQ.get("P", 0))
    Q_val = int(LQ.get("Q", 0))

    d_dt = parse_date_or_none(D)
    e_dt = parse_date_or_none(E)
    hari_inclusive = inclusive_days(d_dt, e_dt)
    hari_str = str(hari_inclusive) if hari_inclusive is not None else ""

    def fmt_n(n: int) -> str:
        return f"{n:,}".replace(",", ".")

    # 1) Baca ukuran template (pakai ukuran halaman template agar 100% selaras)
    if not overlay_template_bytes:
        st.error("Background template PDF belum tersedia. Upload file atau letakkan di assets/spj_blank.pdf.")
        return b""

    base_reader = PdfReader(io.BytesIO(overlay_template_bytes))
    base_page = base_reader.pages[0]
    PAGE_W = float(base_page.mediabox.width)
    PAGE_H = float(base_page.mediabox.height)

    # 2) Gambar teks ke overlay (PDF transparan)
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

    def draw_row(y, value, x_label=120, x_colon=10, x_value=50, size=10, bold=False):
        """
        Template kosong berisi label & tanda ':' pada background.
        Di overlay ini kita hanya menulis nilai, jadi posisikan nilai sedikit ke kanan dari titik dua.
        """
        x0 = 40
        draw_text(x0 + x_label + x_colon + x_value, y, value, size=size, bold=bold)

    # Penempatan koordinat disetel berdasarkan inspeksi template kosong yang kamu kirim. [1](https://asdpindonesiaferry365-my.sharepoint.com/personal/nirwandha_pradana_asdp_id/Documents/Microsoft%20Copilot%20Chat%20Files/spj%20blank.pdf)
    # ===== Identitas =====
    y = PAGE_H - 118
    draw_row(y, "")  # SPPD NO (dikosongkan)
    y -= 18
    draw_row(y, A)  # ATAS NAMA  (*A)
    y -= 18
    draw_row(y, B)  # TEMPAT ASAL (*B)
    y -= 18
    draw_row(y, C)  # TUJUAN      (*C)
    y -= 18
    draw_row(y, D)  # TGL BERANGKAT (*D)
    y -= 18
    draw_row(y, E)  # TGL KEMBALI   (*E)
    y -= 18
    draw_row(y, hari_str)  # JUMLAH HARI (*E-*D inklusif)
    # Kata "Hari" sudah ada pada template, jadi kita tidak menulis ulang.

    # ===== A. Realisasi Biaya Harian =====
    # Koordinat di bawah disesuaikan agar menumpang tepat di area nilai pada template. [1](https://asdpindonesiaferry365-my.sharepoint.com/personal/nirwandha_pradana_asdp_id/Documents/Microsoft%20Copilot%20Chat%20Files/spj%20blank.pdf)
    y = PAGE_H - 270
    draw_text(80, y, "HARI TERTULIS SPPD", size=10)  # label ini sudah ada pada template, tambahkan bila ingin menegaskan

    y -= 18
    draw_text(80, y, "REALISASI", size=10)

    y -= 18
    # Rp. <K>   REALISASI HARI
    draw_text(75, y, fmt_n(K_val), size=10)     # *K
    draw_text(175, y, "REALISASI HARI", size=10)

    y -= 18
    draw_text(40, y, hari_str, size=10)  # jumlah hari
    draw_text(60, y, "Hari", size=10)

    y -= 18
    draw_text(40, y, "SELISIH KURANG (kembali ke karyawan)", size=10)
    y -= 18
    draw_text(75, y, fmt_n(K_val), size=10)  # *K
    draw_text(150, y, "(AKOMODASI DITANGGUNG PANITIA)", size=10)

    y -= 18
    draw_text(40, y, "SELISIH TAMBAH (kembali ke perusahaan)", size=10)
    y -= 18
    draw_text(75, y, "-", size=10)

    # ===== B. Fasilitas Transportasi (Pesawat) =====
    y -= 28
    draw_text(75, y, "Rp.", size=10)
    y -= 18
    draw_text(40, y, "REALISASI", size=10)
    y -= 18
    draw_text(75, y, "-", size=10)
    y -= 18
    draw_text(40, y, "SELISIH KURANG (kembali ke karyawan)", size=10)
    y -= 18
    draw_text(75, y, "-", size=10)
    y -= 18
    draw_text(40, y, "SELISIH TAMBAH (kembali ke perusahaan)", size=10)
    y -= 18
    draw_text(75, y, "-", size=10)

    # ===== C. Penginapan =====
    y -= 28
    draw_text(75, y, "Rp.", size=10)
    y -= 18
    draw_text(40, y, "REALISASI", size=10)
    y -= 18
    draw_text(75, y, "-", size=10)
    draw_text(110, y, "(CTM)", size=10)
    y -= 18
    draw_text(40, y, "SELISIH KURANG (kembali ke karyawan)", size=10)
    y -= 18
    draw_text(75, y, "-", size=10)
    y -= 18
    draw_text(40, y, "SELISIH TAMBAH (kembali ke perusahaan)", size=10)
    y -= 18
    draw_text(75, y, "-", size=10)

    # ===== D. Lain-lain =====
    y -= 28
    # - Bensin
    draw_text(250, y, fmt_n(L_val), size=10)  # *L
    y -= 18
    # - Hotel (CTM)
    draw_text(250, y, fmt_n(M_val), size=10)  # *M
    y -= 18
    # - Toll
    draw_text(250, y, fmt_n(N_val), size=10)  # *N
    y -= 18
    # - Transportasi
    draw_text(250, y, fmt_n(O_val), size=10)  # *O
    y -= 18
    # - Parkir
    draw_text(250, y, fmt_n(P_val), size=10)  # *P
    y -= 18
    # Selisih kurang (kembali ke karyawan): Q
    draw_text(40, y, fmt_n(Q_val), size=10)   # *Q

    # ===== Ringkasan I / II / TOTAL =====
    y -= 28
    draw_text(80, y, fmt_n(Q_val), size=10, bold=True)  # I. TOTAL SELISIH KURANG  (*Q)
    y -= 28
    draw_text(80, y, "-", size=10, bold=True)           # II. TOTAL SELISIH TAMBAH
    y -= 28
    draw_text(80, y, fmt_n(Q_val), size=10, bold=True)  # TOTAL SELISIH (*Q)

    # ===== Mengetahui / TTD =====
    y -= 40
    # Baris jabatan pada template sudah tersedia; kita isi nama:
    draw_text(40, y, (H if H else I), size=10, bold=True)      # kiri – pejabat (*H atau *I)
    draw_text(300, y, A, size=10, bold=True)                   # kanan – pelaksana (*A)

    # Tanggal & catatan
    y -= 24
    draw_text(40, y, D, size=10)   # tanggal berangkat
    draw_text(180, y, E, size=10)  # tanggal kembali
    y -= 18
    # catatan "_Dilarang ..._" dan kode (…) sudah ada pada template

    c.showPage()
    c.save()
    overlay_pdf = packet.getvalue()

    # 3) Tumpuk overlay ke background template
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
        st.warning(f"Gagal overlay di atas template. Mengembalikan overlay saja. Detail: {e}")
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
    4) Klik **Unduh PDF SPJ (Overlay)**.
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
st.subheader("🧩 Template Background (opsional jika file repo tersedia)")

# Coba auto-load dari repo path (agar tidak perlu upload setiap kali)
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

# ========== Export PDF (Overlay) ==========
st.subheader("📄 Export PDF — SPJ (overlay di atas template)")
if st.button("🧾 Unduh PDF SPJ (Overlay)", use_container_width=True):
    if not st.session_state.parsed_AK:
        st.warning("Data A–K belum ada. Silakan parse HTML terlebih dahulu.")
    elif not st.session_state.bg_template_bytes:
        st.warning("Template background belum tersedia. Upload file atau letakkan di assets/spj_blank.pdf.")
    else:
        pdf_bytes = build_spj_pdf_overlay(st.session_state.parsed_AK, totals, st.session_state.bg_template_bytes)
        if pdf_bytes:
            st.download_button(
                "⬇️ Klik untuk mengunduh PDF SPJ (Overlay)",
                pdf_bytes,
                file_name="SPJ_Realisasi_Perjalanan_Dinas_overlay.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
