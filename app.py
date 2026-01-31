import json
import os
import io
import base64
from typing import List, Dict, Optional

import streamlit as st
import streamlit.components.v1 as components

from src.parser import parse_html_to_A_to_K


# =========================
# Helpers
# =========================
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
    """Format ribuan gaya Indonesia: titik pemisah ribuan, prefix IDR."""
    s = f"{n:,}".replace(",", ".")
    return f"IDR {s}"


def fmt_n(n: int) -> str:
    """Format angka (tanpa prefix), contoh 3840000 -> '3.840.000'."""
    return f"{n:,}".replace(",", ".")


def ensure_states():
    if "parsed_AK" not in st.session_state:
        st.session_state.parsed_AK: Dict[str, str | None] = {}
    if "reimburse_rows" not in st.session_state:
        st.session_state.reimburse_rows: List[Dict] = []
    if "totals_LQ" not in st.session_state:
        st.session_state.totals_LQ: Dict[str, int] = {k: 0 for k in list("LMNOPQ")}
    # PDF: template & preview
    if "bg_template_bytes" not in st.session_state:
        st.session_state.bg_template_bytes: Optional[bytes] = None
    if "preview_pdf" not in st.session_state:
        st.session_state.preview_pdf: Optional[bytes] = None
    # Nilai override (opsional)
    if "val_overrides" not in st.session_state:
        st.session_state.val_overrides: Dict[str, str] = {}
    # Koordinat & style per value (A..Q)
    if "coord_style" not in st.session_state:
        # Nilai default koordinat:
        # A diminta default x=190pt, y=666pt; yang lain bisa diset via UI.
        st.session_state.coord_style = {
            # key: {"x": float, "y": float, "size": int, "bold": bool, "fmt": str}
            # fmt: "auto" | "raw" | "number"
            "A": {"x": 190.0, "y": 666.0, "size": 10, "bold": False, "fmt": "raw"},
            "B": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw"},
            "C": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw"},
            "D": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw"},
            "E": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw"},
            "F": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw"},
            "G": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw"},
            "H": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw"},
            "I": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw"},
            "J": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw"},  # days
            "K": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "number"},
            "L": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "number"},
            "M": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "number"},
            "N": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "number"},
            "O": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "number"},
            "P": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "number"},
            "Q": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "number"},
        }


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


def get_value_for_key(key: str) -> str:
    """
    Ambil nilai final untuk key A..Q:
      - cek override (jika user isi manual),
      - jika tidak ada, ambil dari parsed_AK (A..K),
      - untuk L..Q ambil dari totals_LQ,
      - lakukan formatting sesuai 'fmt'.
    """
    # Override manual dari user?
    ov = st.session_state.val_overrides.get(key)
    if ov not in (None, ""):
        return str(ov)

    # Data A..K dari parse
    ak = st.session_state.parsed_AK or {}
    lq = st.session_state.totals_LQ or {}

    # Default text (raw) berdasarkan sumber
    if key in list("ABCDEFGHIJK"):
        raw = ak.get(key)
        # Untuk J (days) kadang text "3" atau "3 Day". Kita ambil digitnya saja.
        if key == "J" and raw:
            digits = "".join(ch for ch in str(raw) if ch.isdigit())
            raw = digits or raw
    elif key in list("LMNOPQ"):
        raw = lq.get(key, 0)
    else:
        raw = ""

    # Formatting sesuai setting
    style = st.session_state.coord_style.get(key, {})
    fmt_mode = style.get("fmt", "raw")

    if fmt_mode == "number":
        try:
            # Raw bisa berupa "IDR 1.200.000" atau int → normalkan dulu
            val = raw
            if isinstance(val, str):
                val = idr_to_int(val)
            if isinstance(val, (int, float)):
                return fmt_n(int(val))
            return str(raw or "")
        except Exception:
            return str(raw or "")

    elif fmt_mode == "raw":
        return str(raw or "")

    # "auto": kalau angka → number, kalau bukan → raw
    try:
        if isinstance(raw, (int, float)):
            return fmt_n(int(raw))
        # string angka?
        test = idr_to_int(str(raw))
        if test > 0:
            return fmt_n(test)
    except Exception:
        pass
    return str(raw or "")


# =========================
# PDF Builder: Multi (A–Q)
# =========================
def build_pdf_multi(
    background_pdf_bytes: bytes,
    items: List[Dict[str, object]],  # [{ "text": str, "x": float, "y": float, "size": int, "bold": bool }, ...]
) -> bytes:
    """
    Tulis beberapa teks (A..Q) di koordinat berbeda dalam satu overlay di atas template PDF.
    """
    if not background_pdf_bytes:
        return b""

    try:
        from reportlab.pdfgen import canvas
        from PyPDF2 import PdfReader, PdfWriter
    except Exception as e:
        st.error(f"Dependency PDF belum terpasang: {e}")
        return b""

    # Baca ukuran halaman template
    try:
        base_reader = PdfReader(io.BytesIO(background_pdf_bytes))
        base_page = base_reader.pages[0]
        page_w = float(base_page.mediabox.width)
        page_h = float(base_page.mediabox.height)
    except Exception as e:
        st.error(f"Gagal membaca template PDF: {e}")
        return b""

    # Overlay
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    for it in items:
        text = str(it.get("text") or "").strip()
        if not text:
            continue
        x = float(it.get("x", 0))
        y = float(it.get("y", 0))
        size = int(it.get("size", 10))
        bold = bool(it.get("bold", False))
        font = "Helvetica-Bold" if bold else "Helvetica"
        try:
            c.setFont(font, size)
        except Exception:
            c.setFont("Helvetica", 10)
        c.drawString(x, y, text)

    c.showPage()
    c.save()
    overlay_pdf = buf.getvalue()

    # Merge
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
        st.error(f"Gagal merge overlay: {e}")
        return overlay_pdf


# =========================
# UI
# =========================
st.set_page_config(page_title="Trip HTML Parser (A–Q) + PDF Overlay", page_icon="🧭", layout="wide")
ensure_states()

st.title("🧭 Trip HTML Parser (A–Q)")
st.caption("Tempel/unggah HTML Trip Detail → Ekstrak A–K → Input Reimburse → Simpan L–Q → PDF Overlay (A–Q).")

with st.expander("Cara pakai (singkat)", expanded=False):
    st.markdown(
        "- **Langkah 1**: Tempel/unggah HTML, klik **Parse HTML** untuk mengambil A–K.\n"
        "- **Langkah 2**: Isi **Reimburse** untuk menghasilkan L–Q.\n"
        "- **Langkah 3**: Siapkan **template PDF** (otomatis dari `assets/spj_blank.pdf` atau upload manual).\n"
        "- **Langkah 4**: Atur **koordinat X/Y** per value (A..Q), pilih **font size**/**bold**.\n"
        "- **Langkah 5**: Klik **Preview** untuk Live View PDF; klik **Download** untuk mengunduh."
    )

# ===== Input HTML =====
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

# ===== Parse A–K =====
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

# ===== Reimburse L–Q =====
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
# PDF Overlay (A–Q) — Koordinat Bebas
# =========================
st.divider()
st.subheader("📄 PDF Overlay (A–Q) — Koordinat Bebas")

# Muat template
DEFAULT_BG_PATH = os.environ.get("SPJ_BG_PATH", "assets/spj_blank.pdf")
if not st.session_state.bg_template_bytes:
    try:
        if os.path.exists(DEFAULT_BG_PATH):
            with open(DEFAULT_BG_PATH, "rb") as f:
                st.session_state.bg_template_bytes = f.read()
            st.info(f"Template background di-load dari: {DEFAULT_BG_PATH}")
    except Exception as e:
        st.warning(f"Tidak bisa membaca {DEFAULT_BG_PATH}: {e}")

tpl_up = st.file_uploader("Atau upload template PDF (1 halaman)", type=["pdf"])
if tpl_up is not None:
    st.session_state.bg_template_bytes = tpl_up.read()
    st.success("Template berhasil dimuat dari upload.")

# Editor nilai & koordinat per key
st.markdown("#### Nilai (opsional override) & Koordinat")

with st.expander("🔧 Atur Nilai Override (opsional)", expanded=False):
    cols = st.columns(4)
    keys1 = list("ABCDEFGHIJ")  # A..J
    keys2 = list("KLMNOPQ")     # K..Q
    for i, k in enumerate(keys1):
        with cols[i % 4]:
            st.session_state.val_overrides[k] = st.text_input(
                f"{k} (override)", value=st.session_state.val_overrides.get(k, "")
            )
    st.markdown("---")
    for i, k in enumerate(keys2):
        with cols[i % 4]:
            st.session_state.val_overrides[k] = st.text_input(
                f"{k} (override)", value=st.session_state.val_overrides.get(k, "")
            )

with st.expander("📍 Atur Koordinat X/Y, Size, Bold, Format", expanded=True):
    # Kelompokkan agar tidak terlalu panjang dalam satu kolom
    groups = [
        ("Identitas (A–E, J)", ["A", "B", "C", "D", "E", "J"]),
        ("Info Lain (F–I, G biasanya jabatan)", ["F", "G", "H", "I"]),
        ("Nominal (K–Q)", ["K", "L", "M", "N", "O", "P", "Q"]),
    ]
    for title, keys in groups:
        st.markdown(f"**{title}**")
        gcols = st.columns(6)
        for k in keys:
            cs = st.session_state.coord_style.get(k, {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw"})
            with gcols[0]:
                st.session_state.coord_style[k]["x"] = st.number_input(f"{k} · X", value=float(cs["x"]), step=1.0, key=f"x_{k}")
            with gcols[1]:
                st.session_state.coord_style[k]["y"] = st.number_input(f"{k} · Y", value=float(cs["y"]), step=1.0, key=f"y_{k}")
            with gcols[2]:
                st.session_state.coord_style[k]["size"] = st.number_input(f"{k} · Size", value=int(cs["size"]), step=1, min_value=6, max_value=72, key=f"s_{k}")
            with gcols[3]:
                st.session_state.coord_style[k]["bold"] = st.checkbox(f"{k} · Bold", value=bool(cs["bold"]), key=f"b_{k}")
            with gcols[4]:
                st.session_state.coord_style[k]["fmt"] = st.selectbox(
                    f"{k} · Format", options=["raw", "number", "auto"], index=["raw","number","auto"].index(cs.get("fmt","raw")), key=f"f_{k}"
                )
            with gcols[5]:
                # Tampilkan nilai aktual yang akan dicetak (read-only)
                st.text_input(f"{k} · Nilai", value=get_value_for_key(k), disabled=True, key=f"v_{k}")

# Tombol preview & download
pcol1, pcol2 = st.columns(2)
with pcol1:
    do_preview = st.button("🔁 Preview PDF (A–Q)", use_container_width=True)
with pcol2:
    do_download = st.button("⬇️ Download PDF (A–Q)", use_container_width=True)

def _items_from_state() -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    for k, style in st.session_state.coord_style.items():
        x = float(style.get("x", 0))
        y = float(style.get("y", 0))
        if x == 0 and y == 0:
            continue  # lewati key yang belum diset koordinatnya
        txt = get_value_for_key(k)
        if not str(txt).strip():
            continue
        items.append({
            "text": txt,
            "x": x,
            "y": y,
            "size": int(style.get("size", 10)),
            "bold": bool(style.get("bold", False)),
        })
    return items

# Generate preview
if do_preview:
    if not st.session_state.bg_template_bytes:
        st.warning("Template PDF belum tersedia. Upload file atau letakkan di assets/spj_blank.pdf.")
    else:
        items = _items_from_state()
        if not items:
            st.warning("Belum ada koordinat yang diisi. Set minimal satu value (mis. B) lalu Preview.")
        else:
            st.session_state.preview_pdf = build_pdf_multi(
                st.session_state.bg_template_bytes, items
            )

# Tampilkan preview (Chrome-safe)
if st.session_state.preview_pdf:
    b64 = base64.b64encode(st.session_state.preview_pdf).decode("utf-8")
    html = f"""
    <div style="height: 920px; width: 100%; border: 1px solid #ddd;">
      <embed
        src="data:application/pdf;base64,{b64}#toolbar=1&navpanes=0&statusbar=0&view=FitH"
        type="application/pdf"
        width="100%"
        height="100%"
      />
      <p style="padding:8px;font-family:sans-serif;">
        Jika PDF tidak tampil, Anda bisa <a download="overlay_A_to_Q.pdf" href="data:application/pdf;base64,{b64}">mengunduhnya di sini</a>.
      </p>
    </div>
    """
    components.html(html, height=940, scrolling=True)
else:
    st.info("Preview belum tersedia. Klik **🔁 Preview PDF (A–Q)** setelah mengatur koordinat.")

# Download
if do_download:
    if not st.session_state.bg_template_bytes:
        st.warning("Template PDF belum tersedia. Upload file atau letakkan di assets/spj_blank.pdf.")
    else:
        items = _items_from_state()
        if not items:
            st.warning("Belum ada koordinat yang diisi.")
        else:
            pdf_bytes = build_pdf_multi(st.session_state.bg_template_bytes, items)
            st.download_button(
                "⬇️ Klik untuk mengunduh PDF (A–Q)",
                data=pdf_bytes,
                file_name="SPJ_A_to_Q_overlay.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
