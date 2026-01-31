import json
import os 
from typing import List, Dict
import streamlit as st

from src.parser import parse_html_to_A_to_K

# -------------------- Helpers --------------------
def idr_to_int(s: str) -> int:
    """
    Konversi teks nominal menjadi integer rupiah.
    Menerima format: 'IDR 1.200.000', '1,200,000', '1200000', dsb.
    Aturan: buang semua karakter non-digit, abaikan desimal.
    """
    if s is None:
        return 0
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    return int(digits) if digits else 0

def fmt_idr(n: int) -> str:
    # Format ribuan gaya Indonesia: titik sebagai pemisah ribuan
    s = f"{n:,}".replace(",", ".")
    return f"IDR {s}"

def ensure_states():
    if "parsed_AK" not in st.session_state:
        st.session_state.parsed_AK: Dict[str, str | None] = {}
    if "reimburse_rows" not in st.session_state:
        # list of dict: {"jenis": "bensin", "nominal": 1200000}
        st.session_state.reimburse_rows: List[Dict] = []
    if "totals_LQ" not in st.session_state:
        # Letters L..Q
        st.session_state.totals_LQ: Dict[str, int] = {k: 0 for k in list("LMNOPQ")}

def recompute_totals():
    """
    Hitung ulang total per jenis dan map ke L..Q
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

    # simpan ke L..P
    LQ = {}
    for jenis, letter in kind_to_letter.items():
        LQ[letter] = totals.get(jenis, 0)

    # Q = total semua
    LQ["Q"] = sum(totals.values())

    st.session_state.totals_LQ = LQ

# =========================
# PDF Builder: Overlay A saja (koordinat bebas)
# =========================
def build_pdf_A_only(
    background_pdf_bytes: bytes,
    text_A: str,
    x: float,
    y: float,
    font_size: int = 10,
    bold: bool = False,
) -> bytes:
    """
    Tulis hanya value A di koordinat (x, y) di atas template PDF 1 halaman.
    (0,0) = kiri-bawah; satuan point.
    """
    if not background_pdf_bytes:
        return b""

    # Lazy import supaya app tidak crash jika dep belum terpasang
    try:
        from reportlab.pdfgen import canvas
    except Exception as e:
        import streamlit as st
        st.error("Package `reportlab` belum terpasang. Tambahkan ke requirements.txt. Detail: " + str(e))
        return b""
    try:
        from PyPDF2 import PdfReader, PdfWriter
    except Exception as e:
        import streamlit as st
        st.error("Package `PyPDF2` belum terpasang. Tambahkan ke requirements.txt. Detail: " + str(e))
        return b""

    # Baca ukuran halaman dari template
    base_reader = PdfReader(io.BytesIO(background_pdf_bytes))
    base_page = base_reader.pages[0]
    page_w = float(base_page.mediabox.width)
    page_h = float(base_page.mediabox.height)

    # Buat overlay transparan
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    font_name = "Helvetica-Bold" if bold else "Helvetica"
    c.setFont(font_name, float(font_size))

    # Tulis nilai A di titik (x, y)
    if text_A:
        c.drawString(float(x), float(y), str(text_A))

    c.showPage()
    c.save()
    overlay_pdf = buf.getvalue()

    # Merge overlay ke background
    overlay_reader = PdfReader(io.BytesIO(overlay_pdf))
    overlay_page = overlay_reader.pages[0]
    base_page.merge_page(overlay_page)

    writer = PdfWriter()
    writer.add_page(base_page)

    out_buf = io.BytesIO()
    writer.write(out_buf)
    return out_buf.getvalue()

# -------------------- UI --------------------
st.set_page_config(page_title="Trip HTML Parser (A–Q)", page_icon="🧭", layout="wide")
ensure_states()

st.title("🧭 Trip HTML Parser (A–Q)")
st.caption("Tempel/unggah HTML Trip Detail → Ekstrak A–K → Input Reimburse → Simpan L–Q.")

with st.expander("Cara pakai", expanded=False):
    st.markdown(
        "- **Langkah 1**: Tempel atau unggah HTML, lalu klik **Parse HTML** untuk mendapatkan A–K.\n"
        "- **Langkah 2**: Di bagian **Reimburse**, pilih jenis biaya dan masukkan nominal, klik **Tambah**.\n"
        "- **Langkah 3**: Lihat tabel, hapus baris jika perlu. Total otomatis tersimpan ke **L–Q**.\n"
        "- **Langkah 4**: Unduh JSON bila diperlukan."
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

# -------------------- Parse A–K --------------------
if parse_btn:
    if not html_text or not html_text.strip():
        st.error("Silakan tempel atau unggah HTML terlebih dahulu.")
        st.stop()

    data_AK = parse_html_to_A_to_K(html_text)
    st.session_state.parsed_AK = data_AK

# Tampilkan A–K jika sudah ada
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

# -------------------- Reimburse Section (L–Q) --------------------
st.subheader("🧾 Reimburse")

# Form input
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
    # Render baris manual agar ada tombol Hapus per baris
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
            # Hapus entry dan hitung ulang
            del st.session_state.reimburse_rows[idx - 1]
            recompute_totals()
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

# Gabungkan A–K + L–Q untuk JSON/unduhan
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

# =========================
# ✍️ Tempatkan value A ke PDF (koordinat bebas)
# =========================
st.divider()
st.subheader("✍️ Tempatkan value **A** ke PDF (koordinat bebas)")

# Pastikan template tersedia
DEFAULT_BG_PATH = os.environ.get("SPJ_BG_PATH", "assets/spj_blank.pdf")
if "bg_template_bytes_A" not in st.session_state:
    st.session_state.bg_template_bytes_A = None

# Coba muat otomatis dari repo (sekali saja)
if not st.session_state.bg_template_bytes_A:
    try:
        if os.path.exists(DEFAULT_BG_PATH):
            with open(DEFAULT_BG_PATH, "rb") as f:
                st.session_state.bg_template_bytes_A = f.read()
            st.info(f"Template PDF dimuat dari: {DEFAULT_BG_PATH}")
    except Exception as e:
        st.warning(f"Tidak bisa membaca {DEFAULT_BG_PATH}: {e}")

# Atau upload manual
tpl_file_A = st.file_uploader("(Opsional) Unggah template PDF untuk penempatan A", type=["pdf"], key="tpl_for_A")
if tpl_file_A is not None:
    st.session_state.bg_template_bytes_A = tpl_file_A.read()
    st.success("Template untuk penempatan A berhasil dimuat dari upload.")

# Ambil value A dari hasil parse (jika ada)
value_A = st.session_state.parsed_AK.get("A") if st.session_state.parsed_AK else ""
st.text_input("Nilai A (Employee Name)", value=value_A or "", key="val_A_override", help="Bisa diedit jika perlu")

colA1, colA2, colA3, colA4 = st.columns(4)
with colA1:
    x_A = st.number_input("Koordinat X (pt; 0=tepi kiri)", value=228.0, step=1.0)
with colA2:
    y_A = st.number_input("Koordinat Y (pt; 0=tepi bawah)", value=700.0, step=1.0)
with colA3:
    size_A = st.number_input("Ukuran font", value=10, step=1, min_value=6, max_value=48)
with colA4:
    bold_A = st.checkbox("Bold", value=False)

colB1, colB2 = st.columns([1,1])
with colB1:
    do_preview_A = st.button("🔁 Preview A di PDF", use_container_width=True)
with colB2:
    do_download_A = st.button("⬇️ Unduh PDF (A saja)", use_container_width=True)

# State untuk preview
if "preview_A_pdf" not in st.session_state:
    st.session_state.preview_A_pdf = None

# Render preview
if do_preview_A:
    if not st.session_state.bg_template_bytes_A:
        st.warning("Template PDF belum tersedia. Upload file atau letakkan di assets/spj_blank.pdf.")
    else:
        pdf_bytes_A = build_pdf_A_only(
            background_pdf_bytes=st.session_state.bg_template_bytes_A,
            text_A=st.session_state.get("val_A_override") or "",
            x=x_A, y=y_A,
            font_size=size_A,
            bold=bold_A,
        )
        st.session_state.preview_A_pdf = pdf_bytes_A

# Tampilkan preview jika ada
if st.session_state.preview_A_pdf:
    try:
        import base64
        import streamlit.components.v1 as components
        b64 = base64.b64encode(st.session_state.preview_A_pdf).decode("utf-8")
        components.html(
            f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="900px" style="border:none;"></iframe>',
            height=920,
            scrolling=True,
        )
    except Exception as e:
        st.warning(f"Gagal menampilkan preview inline: {e}")

# Tombol unduh
if do_download_A:
    if not st.session_state.bg_template_bytes_A:
        st.warning("Template PDF belum tersedia. Upload file atau letakkan di assets/spj_blank.pdf.")
    else:
        pdf_bytes_A = build_pdf_A_only(
            background_pdf_bytes=st.session_state.bg_template_bytes_A,
            text_A=st.session_state.get("val_A_override") or "",
            x=x_A, y=y_A,
            font_size=size_A,
            bold=bold_A,
        )
        st.download_button(
            "⬇️ Klik untuk menyimpan PDF (A)",
            data=pdf_bytes_A,
            file_name="SPJ_A_only.pdf",
            mime="application/pdf",
            use_container_width=True,
        )
