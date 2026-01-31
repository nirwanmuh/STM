# app.py
import io
import json
from datetime import datetime
from typing import Optional, Dict, List

import streamlit as st

from src.parser import parse_html_to_A_to_K


# =========================
# Helpers
# =========================
def idr_to_int(s: str) -> int:
    """
    Konversi 'IDR 1.200.000' / '1,200,000' / '1200000' -> 1200000 (int).
    """
    if s is None:
        return 0
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    return int(digits) if digits else 0


def fmt_idr(n: int) -> str:
    """
    Format ke 'IDR 1.234.567' (titik pemisah ribuan).
    """
    s = f"{n:,}".replace(",", ".")
    return f"IDR {s}"


def ensure_states():
    """
    Inisialisasi session_state.
    """
    if "parsed_AK" not in st.session_state:
        st.session_state.parsed_AK: Dict[str, Optional[str]] = {}
    if "reimburse_rows" not in st.session_state:
        st.session_state.reimburse_rows: List[Dict] = []
    if "totals_LQ" not in st.session_state:
        st.session_state.totals_LQ: Dict[str, int] = {k: 0 for k in list("LMNOPQ")}


def recompute_totals():
    """
    Hitung ulang total per jenis dan map ke L..Q.
    """
    kind_to_letter = {
        "bensin": "L",
        "hotel": "M",
        "toll": "N",
        "transportasi": "O",
        "parkir": "P",
    }
    totals = {k: 0 for k in kind_to_letter.keys()}
    for row in st.session_state.reimburse_rows:
        j = row["jenis"].lower()
        totals[j] = totals.get(j, 0) + int(row["nominal"])

    LQ = {}
    for jenis, letter in kind_to_letter.items():
        LQ[letter] = totals.get(jenis, 0)
    LQ["Q"] = sum(totals.values())
    st.session_state.totals_LQ = LQ


def parse_date_or_none(s: Optional[str]) -> Optional[datetime]:
    """
    Parse tanggal seperti '19 January, 2026' -> datetime, jika gagal -> None.
    """
    if not s:
        return None
    for fmt in ("%d %B, %Y", "%d %b, %Y", "%d %B %Y", "%d %b %Y", "%d/%B/%Y", "%d/%b/%Y"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def inclusive_days(d1: Optional[datetime], d2: Optional[datetime]) -> Optional[int]:
    """
    Selisih hari inklusif (contoh: 19-21 = 3).
    """
    if not d1 or not d2:
        return None
    return (d2.date() - d1.date()).days + 1


# =========================
# PDF Builder (Exact Layout)
# =========================
def build_spj_pdf_exact(
    AK: Dict[str, Optional[str]],
    LQ: Dict[str, int],
    overlay_template_bytes: Optional[bytes] = None
) -> bytes:
    """
    Builder PDF 'Exact Layout' meniru contoh.
    - Lazy import reportlab & PyPDF2 supaya app tidak crash jika dependency belum terpasang.
    - Jika overlay_template_bytes diberikan (PDF 1 halaman), kita jadikan background dan menulis nilai A–Q di atasnya.
    """
    # Lazy import; tampilkan pesan jika dependency belum ada
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
    except Exception as e:
        st.error(
            "Package `reportlab` belum terpasang. Tambahkan ke `requirements.txt` "
            "lalu deploy ulang. Detail: " + str(e)
        )
        return b""

    PdfReader = PdfWriter = None
    if overlay_template_bytes is not None:
        try:
            from PyPDF2 import PdfReader as _PdfReader, PdfWriter as _PdfWriter
            PdfReader, PdfWriter = _PdfReader, _PdfWriter
        except Exception as e:
            st.warning(
                "Package `PyPDF2` belum terpasang, overlay template PDF di-skip. "
                "Tambahkan `PyPDF2` ke requirements.txt jika ingin overlay. Detail: " + str(e)
            )
            overlay_template_bytes = None

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

    def fmt_n(n: int) -> str:
        # contoh output: "2.800.000"
        return f"{n:,}".replace(",", ".")

    # Ukuran kertas: default A4 portrait
    PAGE_W, PAGE_H = A4
    if overlay_template_bytes and PdfReader:
        try:
            base_reader = PdfReader(io.BytesIO(overlay_template_bytes))
            page0 = base_reader.pages[0]
            PAGE_W = float(page0.mediabox.width)
            PAGE_H = float(page0.mediabox.height)
        except Exception:
            pass

    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=(PAGE_W, PAGE_H))

    # Util tulis teks
    def draw_text(x, y, text, size=10, bold=False, align="left"):
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, size)
        if align == "left":
            c.drawString(x, y, text)
        elif align == "center":
            c.drawCentredString(x, y, text)
        elif align == "right":
            c.drawRightString(x, y, text)

    def draw_row(y, label, value, label_w=120, colon_w=10, size=10, bold_label=False):
        x0 = 40
        draw_text(x0, y, label, size=size, bold=bold_label)
        draw_text(x0 + label_w, y, ":", size=size)
        draw_text(x0 + label_w + colon_w, y, value, size=size)

    # ===== Header =====
    draw_text(PAGE_W/2, PAGE_H - 60,
              "FORMULIR PERHITUNGAN REALISASI BIAYA PERJALANAN DINAS/ PINDAH",
              size=11, bold=True, align="center")

    # ===== Identitas =====
    y = PAGE_H - 100
    draw_row(y, "SPPD NO", "")
    y -= 16
    draw_row(y, "ATAS NAMA", A)      # *A
    y -= 16
    draw_row(y, "TEMPAT ASAL", B)    # *B
    y -= 16
    draw_row(y, "TUJUAN", C)         # *C
    y -= 16
    draw_row(y, "TGL BERANGKAT", D)  # *D
    y -= 16
    draw_row(y, "TGL KEMBALI", E)    # *E
    y -= 16
    hari_str = str(hari_inclusive) if hari_inclusive is not None else ""
    draw_row(y, "JUMLAH HARI", f"{hari_str}", size=10)
    draw_text(40 + 120 + 10 + 50, y, "Hari", size=10)

    # ===== A. Realisasi Biaya Harian =====
    y -= 28
    draw_text(40, y, "A. REALISASI BIAYA HARIAN:", size=10, bold=True)
    y -= 18
    draw_text(40, y, "PENERIMAAN", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, "HARI TERTULIS SPPD", size=10)
    y -= 16
    draw_text(40, y, "REALISASI", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, fmt_n(K_val), size=10); draw_text(180, y, "REALISASI HARI", size=10)
    y -= 16
    draw_text(40, y, hari_str, size=10); draw_text(60, y, "Hari", size=10)
    y -= 16
    draw_text(40, y, "SELISIH KURANG (kembali ke karyawan)", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, fmt_n(K_val), size=10); draw_text(150, y, "(AKOMODASI DITANGGUNG PANITIA)", size=10)
    y -= 16
    draw_text(40, y, "SELISIH TAMBAH (kembali ke perusahaan)", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, "-", size=10)

    # ===== B. Transportasi (Pesawat) =====
    y -= 24
    draw_text(40, y, "B. REALISASI BIAYA FASILITAS TRANSPORTASI (PESAWAT):", size=10, bold=True)
    y -= 18
    draw_text(40, y, "PENERIMAAN", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10)
    y -= 16
    draw_text(40, y, "REALISASI", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, "-", size=10)
    y -= 16
    draw_text(40, y, "SELISIH KURANG (kembali ke karyawan)", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, "-", size=10)
    y -= 16
    draw_text(40, y, "SELISIH TAMBAH (kembali ke perusahaan)", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, "-", size=10)

    # ===== C. Penginapan =====
    y -= 24
    draw_text(40, y, "C. REALISASI BIAYA PENGINAPAN:", size=10, bold=True)
    y -= 18
    draw_text(40, y, "PENERIMAAN", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10)
    y -= 16
    draw_text(40, y, "REALISASI", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, "-", size=10); draw_text(110, y, "(CTM)", size=10)
    y -= 16
    draw_text(40, y, "SELISIH KURANG (kembali ke karyawan)", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, "-", size=10)
    y -= 16
    draw_text(40, y, "SELISIH TAMBAH (kembali ke perusahaan)", size=10)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, "-", size=10)

    # ===== D. Lain-lain =====
    y -= 24
    draw_text(40, y, "D. JENIS BIAYA LAIN-LAIN:", size=10, bold=True)
    y -= 18
    draw_text(40, y, "- REALISASI BENSIN", size=10);        draw_text(220, y, "Rp.", size=10); draw_text(250, y, fmt_n(L_val), size=10)
    y -= 16
    draw_text(40, y, "- REALISASI HOTEL (CTM)", size=10);    draw_text(220, y, "Rp.", size=10); draw_text(250, y, fmt_n(M_val), size=10)
    y -= 16
    draw_text(40, y, "- REALISASI TOLL", size=10);           draw_text(220, y, "Rp", size=10);  draw_text(250, y, fmt_n(N_val), size=10)
    y -= 16
    draw_text(40, y, "- REALISASI TRANSPORTASI", size=10);   draw_text(220, y, "Rp", size=10);  draw_text(250, y, fmt_n(O_val), size=10)
    y -= 16
    draw_text(40, y, "- REALISASI PARKIR", size=10);         draw_text(220, y, "Rp", size=10);  draw_text(250, y, fmt_n(P_val), size=10)
    y -= 16
    draw_text(40, y, "SELISIH KURANG (kembali ke karyawan)", size=10)
    y -= 16
    draw_text(40, y, fmt_n(Q_val), size=10)  # *Q

    # ===== Ringkasan =====
    y -= 24
    draw_text(40, y, "I. TOTAL SELISIH KURANG :", size=10, bold=True)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, fmt_n(Q_val), size=10, bold=True)
    y -= 16
    draw_text(40, y, "( total kembali ke karyawan)", size=9)
    y -= 20

    draw_text(40, y, "II. TOTAL SELISIH TAMBAH :", size=10, bold=True)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, "-", size=10, bold=True)
    y -= 16
    draw_text(40, y, "(total kembali ke perusahaan)", size=9)
    y -= 20

    draw_text(40, y, "TOTAL SELISIH :", size=10, bold=True)
    y -= 16
    draw_text(40, y, "Rp.", size=10); draw_text(80, y, fmt_n(Q_val), size=10, bold=True)

    # ===== Mengetahui / TTD =====
    y -= 40
    draw_text(40, y, "Mengetahui", size=10)
    y -= 18
    draw_text(40, y, "Pemimpin Unit Kerja/Fungsi", size=10)
    draw_text(PAGE_W - 220, y, "Pelaksana Perjalanan Dinas", size=10)

    y -= 36
    draw_text(40, y, (H if H else I), size=10, bold=True)     # kiri (pejabat)
    draw_text(PAGE_W - 220, y, A, size=10, bold=True)         # kanan (pelaksana)

    # Footnote tanggal/jabatan
    y -= 28
    draw_text(40, y, D, size=10)
    draw_text(180, y, E, size=10)
    y -= 16
    draw_text(40, y, "_Dilarang Mengcopy / Menyebarluaskan Tanpa Izin MR _", size=9)
    y -= 16
    if G:
        draw_text(40, y, G, size=10)

    # Finish
    c.showPage()
    c.save()
    overlay_pdf = packet.getvalue()

    # Jika tidak ada background template → langsung return
    if not overlay_template_bytes:
        return overlay_pdf

    # Overlay di atas template
    if not (PdfReader and PdfWriter):
        return overlay_pdf  # fallback aman

    try:
        base_reader = PdfReader(io.BytesIO(overlay_template_bytes))
        base_page = base_reader.pages[0]

        overlay_reader = PdfReader(io.BytesIO(overlay_pdf))
        overlay_page = overlay_reader.pages[0]

        # tumpuk teks di atas background
        base_page.merge_page(overlay_page)

        from PyPDF2 import PdfWriter as _PdfWriter  # ensure available
        writer = _PdfWriter()
        writer.add_page(base_page)
        out_buf = io.BytesIO()
        writer.write(out_buf)
        return out_buf.getvalue()
    except Exception as e:
        st.warning(f"Gagal menerapkan overlay template, gunakan layout tanpa background. Detail: {e}")
        return overlay_pdf


# =========================
# UI (Streamlit)
# =========================
st.set_page_config(page_title="Trip HTML Parser (A–Q) + SPJ PDF", page_icon="🧭", layout="wide")
ensure_states()

st.title("🧭 Trip HTML Parser (A–Q) + SPJ PDF")
st.caption("Tempel/unggah HTML → Ekstrak A–K → Input Reimburse (L–Q) → Unduh PDF SPJ.")

with st.expander("Cara pakai", expanded=False):
    st.markdown(
        "- **Langkah 1**: Tempel atau unggah HTML, lalu klik **Parse HTML** untuk mendapatkan A–K.\n"
        "- **Langkah 2**: Isi **Reimburse** (bensin/hotel/toll/transportasi/parkir) lalu klik **Tambah**; bisa berkali-kali dan hapus baris.\n"
        "- **Langkah 3**: Klik **Unduh PDF SPJ (Exact Layout)**. (Opsional) unggah **PDF template kosong** sebagai background agar identik 100%.\n"
    )

tab1, tab2 = st.tabs(["📄 Tempel HTML", "📤 Unggah File HTML"])
html_text = ""

with tab1:
    html_text_input = st.text_area(
        "Tempel HTML kamu di sini",
        height=420,
        placeholder="Tempel seluruh HTML Trip Detail di sini...",
    )
    if html_text_input:
        html_text = html_text_input

with tab2:
    uploaded = st.file_uploader("Unggah file .html", type=["html", "htm"])
    if uploaded is not None:
        html_text = uploaded.read().decode("utf-8", errors="ignore")

parse_btn = st.button("🔎 Parse HTML", type="primary", use_container_width=True)

# -------- Parse A–K --------
if parse_btn:
    if not html_text or not html_text.strip():
        st.error("Silakan tempel atau unggah HTML terlebih dahulu.")
        st.stop()
    data_AK = parse_html_to_A_to_K(html_text)
    st.session_state.parsed_AK = data_AK

# Tampilkan A–K jika ada
if st.session_state.parsed_AK:
    st.subheader("Hasil Ekstraksi **A–K**")
    data = st.session_state.parsed_AK
    col1, col2 = st.columns(2)
    with col1:
        st.write("**A** – Employee Name:", data.get("A"))
        st.write("**B** – Trip From:", data.get("B"))
        st.write("**C** – Trip To:", data.get("C"))
        st.write("**D** – Depart Date:", data.get("D"))
        st.write("**E** – Return Date:", data.get("E"))
    with col2:
        st.write("**F** – Purpose:", data.get("F"))
        st.write("**G** – Position:", data.get("G"))
        st.write("**H** – (Timeline) Role:", data.get("H"))
        st.write("**I** – (Timeline) By:", data.get("I"))
        st.write("**J** – Daily Allowance (Days):", data.get("J"))
        st.write("**K** – Daily Allowance Total:", data.get("K"))

    st.divider()

# -------- Reimburse Section (L–Q) --------
st.subheader("🧾 Reimburse")

with st.form("reimburse_form", clear_on_submit=True):
    jenis = st.selectbox(
        "Jenis biaya",
        options=["bensin", "hotel", "toll", "transportasi", "parkir"],
        index=0,
        help="Pilih kategori reimburse",
    )
    nominal_text = st.text_input(
        "Nominal (contoh: 1200000 atau IDR 1.200.000)",
        value="",
        help="Masukkan angka saja atau boleh pakai format IDR/berpemisah ribuan",
    )
    submitted = st.form_submit_button("➕ Tambah", use_container_width=True)

    if submitted:
        nominal_val = idr_to_int(nominal_text)
        if nominal_val <= 0:
            st.warning("Nominal harus lebih dari 0.")
        else:
            st.session_state.reimburse_rows.append({"jenis": jenis, "nominal": nominal_val})
            recompute_totals()
            st.success(f"Berhasil menambah {jenis} sebesar {fmt_idr(nominal_val)}")

# Tabel Reimburse
st.markdown("### Tabel Reimburse")
if not st.session_state.reimburse_rows:
    st.info("Belum ada data reimburse. Tambahkan melalui form di atas.")
else:
    header_cols = st.columns([0.7, 3, 3, 2])
    header_cols[0].markdown("**No.**")
    header_cols[1].markdown("**Jenis**")
    header_cols[2].markdown("**Nominal**")
    header_cols[3].markdown("**Aksi**")

    for idx, row in enumerate(st.session_state.reimburse_rows, start=1):
        c1, c2, c3, c4 = st.columns([0.7, 3, 3, 2])
        c1.write(idx)
        c2.write(row["jenis"].capitalize())
        c3.write(fmt_idr(int(row["nominal"])))
        if c4.button("Hapus", key=f"del_{idx}", use_container_width=True):
            del st.session_state.reimburse_rows[idx - 1]
            recompute_totals()
            try:
                st.rerun()
            except Exception:
                st.experimental_rerun()

# Total per jenis & map ke L..Q
recompute_totals()
totals = st.session_state.totals_LQ

st.markdown("### Total per Jenis (tersimpan ke value **L–Q**)")
tcols = st.columns(6)
tcols[0].metric("**L – Bensin**", fmt_idr(totals["L"]))
tcols[1].metric("**M – Hotel**", fmt_idr(totals["M"]))
tcols[2].metric("**N – Toll**", fmt_idr(totals["N"]))
tcols[3].metric("**O – Transportasi**", fmt_idr(totals["O"]))
tcols[4].metric("**P – Parkir**", fmt_idr(totals["P"]))
tcols[5].metric("**Q – Total Semua**", fmt_idr(totals["Q"]))

# Gabungan JSON A–Q
combined = {
    **st.session_state.parsed_AK,
    **{k: totals[k] for k in "LMNOPQ"},
}

st.divider()
st.subheader("JSON (A–Q)")
json_str = json.dumps(combined, ensure_ascii=False, indent=2)
st.code(json_str, language="json")
st.download_button(
    label="💾 Unduh JSON (A–Q)",
    data=json_str,
    file_name="trip_A_to_Q.json",
    mime="application/json",
    use_container_width=True,
)

# -------- Export PDF --------
st.divider()
st.subheader("📄 Export PDF — Format SPJ (Exact Layout)")

bg_file = st.file_uploader("Opsional: unggah PDF template kosong sebagai background", type=["pdf"], key="bg_tpl")

if st.button("🧾 Unduh PDF SPJ (Exact Layout)", use_container_width=True):
    if not st.session_state.parsed_AK:
        st.warning("Data A–K belum ada. Silakan parse HTML terlebih dahulu.")
    else:
        bg_bytes = bg_file.read() if bg_file is not None else None
        pdf_bytes = build_spj_pdf_exact(st.session_state.parsed_AK, totals, overlay_template_bytes=bg_bytes)
        if pdf_bytes:
            st.download_button(
                label="⬇️ Klik untuk mengunduh PDF SPJ (Exact Layout)",
                data=pdf_bytes,
                file_name="SPJ_Realisasi_Perjalanan_Dinas_exact.pdf",
                mime="application/pdf",
                use_container_width=True,
            )

# -------- (Opsional) Cek dependency --------
with st.expander("🔎 Cek dependency PDF (opsional)"):
    if st.button("Cek sekarang"):
        try:
            import reportlab  # type: ignore
            st.success(f"reportlab OK (version {getattr(reportlab, '__version__', 'unknown')})")
        except Exception as e:
            st.error(f"reportlab belum terpasang: {e}")

        try:
            import PyPDF2  # type: ignore
            st.info(f"PyPDF2 OK (version {getattr(PyPDF2, '__version__', 'unknown')})")
        except Exception:
            st.warning("PyPDF2 belum terpasang (opsional).")
