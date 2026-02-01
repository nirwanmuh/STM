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
    """'IDR 1.200.000' / '1,200,000' / '1200000' -> 1200000"""
    if s is None:
        return 0
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    return int(digits) if digits else 0


def fmt_idr(n: int) -> str:
    s = f"{n:,}".replace(",", ".")
    return f"IDR {s}"


def fmt_n(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def parse_date_or_none(s: Optional[str]):
    """Coba parse beberapa format tanggal EN; gagal -> None."""
    if not s:
        return None
    from datetime import datetime
    for fmt in ("%d %B, %Y", "%d %b, %Y", "%d %B %Y", "%d %b %Y",
                "%d/%B/%Y", "%d/%b/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except Exception:
            continue
    return None


def day_diff_inclusive(D: Optional[str], E: Optional[str]) -> Optional[int]:
    """
    Hitung (E - D + 1) hari (INKLUSIF): 19..21 -> 3. Gagal parse -> None.
    """
    d1 = parse_date_or_none(D)
    d2 = parse_date_or_none(E)
    if not d1 or not d2:
        return None
    return (d2.date() - d1.date()).days + 1


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
    # Override nilai (opsional)
    if "val_overrides" not in st.session_state:
        st.session_state.val_overrides: Dict[str, str] = {}
    # Gaya/koordinat per value (tambahkan "align": "left|center|right")
    if "coord_style" not in st.session_state:
        st.session_state.coord_style = {
            # A–E, J kiri (fixed). J kiri ditulis di (190,600,size=9) dengan nilai (E-D+1).
            "A": {"x": 190.0, "y": 666.0, "size": 9, "bold": False, "fmt": "raw", "from_right": False, "align": "left",   "locked": True},
            "B": {"x": 190.0, "y": 652.5, "size": 9, "bold": False, "fmt": "raw", "from_right": False, "align": "left",   "locked": True},
            "C": {"x": 190.0, "y": 639.0, "size": 9, "bold": False, "fmt": "raw", "from_right": False, "align": "left",   "locked": True},
            "D": {"x": 190.0, "y": 625.5, "size": 9, "bold": False, "fmt": "raw", "from_right": False, "align": "left",   "locked": True},
            "E": {"x": 190.0, "y": 612.0, "size": 9, "bold": False, "fmt": "raw", "from_right": False, "align": "left",   "locked": True},
            "J": {"x": 190.0, "y": 600.0, "size": 9, "bold": False, "fmt": "raw", "from_right": False, "align": "left",   "locked": True},

            # F–I dari kiri dan editable; G/H/I rata tengah (center) sesuai permintaan.
            "F": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw", "from_right": False, "align": "left",   "locked": False},
            "G": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw", "from_right": False, "align": "center", "locked": False},
            "H": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw", "from_right": False, "align": "center", "locked": False},
            "I": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "fmt": "raw", "from_right": False, "align": "center", "locked": False},

            # K–Q: X diisi sebagai jarak dari kanan & teks rata kanan.
            # Kunci koordinat K–P sesuai Mas; Q dibiarkan editable (sekarang bisa atur dari UI).
            "K": {"x": 260.0, "y": 548.0, "size": 9, "bold": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "L": {"x": 260.0, "y": 313.0, "size": 9, "bold": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "M": {"x": 260.0, "y": 299.0, "size": 9, "bold": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "N": {"x": 260.0, "y": 286.0, "size": 9, "bold": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "O": {"x": 260.0, "y": 273.0, "size": 9, "bold": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "P": {"x": 260.0, "y": 260.0, "size": 9, "bold": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "Q": {"x": 0.0,   "y": 0.0,   "size": 10,"bold": False, "fmt": "number", "from_right": True, "align": "right", "locked": False},
        }
    # Item duplikasi (hard-coded): K lagi & J kanan (REALISASI HARI)
    if "extra_items" not in st.session_state:
        st.session_state.extra_items = {
            # K kedua @ (Xr=260, Y=534)
            "K_DUP": {"key": "K", "x": 260.0, "y": 534.0, "size": 9, "bold": False, "from_right": True, "align": "right"},
            # J kanan @ (Xr=110, Y=534) -> pakai J hasil parsing (digit)
            "J_RIGHT": {"key": "J", "x": 110.0, "y": 534.0, "size": 9, "bold": False, "from_right": True, "align": "right"},
        }


def recompute_totals():
    """Hitung ulang total per jenis dan map ke L..Q"""
    kind_to_letter = {"bensin": "L", "hotel": "M", "toll": "N", "transportasi": "O", "parkir": "P"}
    totals = {k: 0 for k in kind_to_letter.keys()}
    for row in st.session_state.reimburse_rows:
        j = row["jenis"].lower()
        totals[j] = totals.get(j, 0) + int(row["nominal"])
    LQ = {letter: totals.get(jenis, 0) for jenis, letter in kind_to_letter.items()}
    LQ["Q"] = sum(LQ.values())
    st.session_state.totals_LQ = LQ


def get_value_for_key(key: str) -> str:
    """Ambil nilai final untuk key A..Q + formatting per 'fmt'."""
    ov = st.session_state.val_overrides.get(key)
    if ov not in (None, ""):
        return str(ov)

    ak = st.session_state.parsed_AK or {}
    lq = st.session_state.totals_LQ or {}

    if key in list("ABCDEFGHIJK"):
        raw = ak.get(key)
        if key == "J" and raw:
            digits = "".join(ch for ch in str(raw) if ch.isdigit())
            raw = digits or raw
    elif key in list("LMNOPQ"):
        raw = lq.get(key, 0)
    else:
        raw = ""

    style = st.session_state.coord_style.get(key, {})
    fmt_mode = style.get("fmt", "raw")

    if fmt_mode == "number":
        try:
            val = raw
            if isinstance(val, str):
                val = idr_to_int(val)
            if isinstance(val, (int, float)):
                return fmt_n(int(val))
        except Exception:
            pass
        return str(raw or "")

    if fmt_mode == "auto":
        try:
            if isinstance(raw, (int, float)):
                return fmt_n(int(raw))
            test = idr_to_int(str(raw))
            if test > 0:
                return fmt_n(test)
        except Exception:
            pass
        return str(raw or "")

    return str(raw or "")


# =========================
# PDF Builder: Multi (A–Q) + alignment
# =========================
def build_pdf_multi(background_pdf_bytes: bytes, items: List[Dict[str, object]]) -> bytes:
    """
    Gambar semua teks pada posisi/format yang diberikan.
      - from_right=True -> anchor = page_w - x_input
      - align: "left"|"center"|"right"
      - Kombinasi:
          * from_right=True + align="right"  -> drawRightString(page_w - x, y, text)
          * from_right=False + align="center"-> drawCentredString(x, y, text)
          * dst.
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

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_w, page_h))

    for it in items:
        text = str(it.get("text") or "").strip()
        if not text:
            continue

        x_in = float(it.get("x", 0))  # untuk from_right=True, ini adalah jarak dari kanan
        y = float(it.get("y", 0))
        size = int(it.get("size", 10))
        bold = bool(it.get("bold", False))
        from_right = bool(it.get("from_right", False))
        align = (it.get("align") or "left").lower()

        font = "Helvetica-Bold" if bold else "Helvetica"
        try:
            c.setFont(font, size)
        except Exception:
            c.setFont("Helvetica", 10)

        # Hitung anchor X
        x_anchor = (page_w - x_in) if from_right else x_in

        # Gambar sesuai alignment
        if align == "right":
            c.drawRightString(x_anchor, y, text)
        elif align == "center":
            c.drawCentredString(x_anchor, y, text)
        else:
            c.drawString(x_anchor, y, text)

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
st.caption("Tempel/unggah HTML → A–K → Reimburse → L–Q → PDF Overlay (A–Q).")

with st.expander("Cara pakai (singkat)", expanded=False):
    st.markdown(
        "- **Langkah 1**: Tempel/unggah HTML, klik **Parse HTML** untuk mengambil A–K.\n"
        "- **Langkah 2**: Isi **Reimburse** untuk menghasilkan L–Q.\n"
        "- **Langkah 3**: Siapkan **template PDF** (otomatis dari `assets/spj_blank.pdf` atau upload manual).\n"
        "- **Langkah 4**: A–E,J fixed; K–Q: X dari kanan & rata kanan (Q sekarang bisa diatur). F,G,H,I: X dari kiri, G/H/I **rata tengah**.\n"
        "- **Langkah 5**: Preview & Download."
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
    st.session_state.parsed_AK = parse_html_to_A_to_K(html_text)

# Hasil A–K
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
    jenis = st.selectbox("Jenis biaya", options=["bensin", "hotel", "toll", "transportasi", "parkir"], index=0)
    nominal_text = st.text_input("Nominal (contoh: 1200000 atau IDR 1.200.000)", value="")
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
    st.info("Belum ada data reimburse.")
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

# Total L–Q
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

# JSON A–Q
combined = {**st.session_state.parsed_AK, **{k: totals[k] for k in "LMNOPQ"}}
st.divider()
st.subheader("JSON (A–Q)")
json_str = json.dumps(combined, ensure_ascii=False, indent=2)
st.code(json_str, language="json")
st.download_button("💾 Unduh JSON (A–Q)", data=json_str, file_name="trip_A_to_Q.json", mime="application/json", use_container_width=True)

# =========================
# PDF Overlay (A–Q)
# =========================
st.divider()
st.subheader("📄 PDF Overlay (A–Q)")

# Template
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

# ====== Panel koordinat ======
with st.expander("📍 Koordinat & Style", expanded=True):
    # A–E,J: fixed (disabled)
    st.markdown("**Identitas (A–E, J) – fixed**")
    fixed_keys = ["A", "B", "C", "D", "E", "J"]
    fcols = st.columns(6)
    for i, k in enumerate(fixed_keys):
        cs = st.session_state.coord_style[k]
        with fcols[i]:
            st.number_input(f"{k} · X", value=float(cs["x"]), step=0.5, disabled=True, key=f"fx_{k}")
            st.number_input(f"{k} · Y", value=float(cs["y"]), step=0.5, disabled=True, key=f"fy_{k}")
            st.number_input(f"{k} · Size", value=int(cs["size"]), step=1, min_value=6, max_value=72, disabled=True, key=f"fs_{k}")
    st.caption("Koordinat & size A–E,J dikunci. Nilainya boleh dioverride di panel 'Override Nilai' bila perlu.")

    # F–I: editable dari kiri. G/H/I dipaksakan align=center (X = titik tengah).
    st.markdown("**Info Lain (F–I) – dari kiri; G/H/I rata tengah**")
    group_fi = ["F", "G", "H", "I"]
    gcols = st.columns(4)
    for i, k in enumerate(group_fi):
        cs = st.session_state.coord_style[k]
        with gcols[i]:
            # Label khusus agar jelas bahwa G/H/I adalah titik tengah
            x_label = f"{k} · X{' (titik tengah)' if k in ['G','H','I'] else ' (dari kiri)'}"
            st.session_state.coord_style[k]["x"] = st.number_input(x_label, value=float(cs["x"]), step=1.0, key=f"x_{k}")
            st.session_state.coord_style[k]["y"] = st.number_input(f"{k} · Y", value=float(cs["y"]), step=1.0, key=f"y_{k}")
            st.session_state.coord_style[k]["size"] = st.number_input(f"{k} · Size", value=int(cs["size"]), step=1, min_value=6, max_value=72, key=f"s_{k}")
            st.session_state.coord_style[k]["bold"] = st.checkbox(f"{k} · Bold", value=bool(cs["bold"]), key=f"b_{k}")
            # Align tidak diekspos di UI untuk G/H/I (dipaksa center), F tetap left—jadi tidak ditampilkan.

    # K–Q: X = jarak dari kanan, tulisan rata kanan. Q sekarang editable.
    st.markdown("**Nominal (K–Q) – X = jarak dari kanan (rata kanan)**")
    group_kq = ["K", "L", "M", "N", "O", "P", "Q"]
    cols_kq = st.columns(7)
    for i, k in enumerate(group_kq):
        cs = st.session_state.coord_style[k]
        with cols_kq[i]:
            st.number_input(f"{k} · X dari kanan", value=float(cs["x"]), step=1.0, key=f"x_{k}_right", disabled=bool(cs.get("locked", False)))
            st.number_input(f"{k} · Y", value=float(cs["y"]), step=1.0, key=f"y_{k}", disabled=bool(cs.get("locked", False)))
            st.number_input(f"{k} · Size", value=int(cs["size"]), step=1, min_value=6, max_value=72, key=f"s_{k}", disabled=bool(cs.get("locked", False)))
            st.checkbox(f"{k} · Bold", value=bool(cs["bold"]), key=f"b_{k}", disabled=bool(cs.get("locked", False)))
            # Format dikunci default number untuk K–Q; tidak perlu UI tambahan.

# Override nilai (opsional)
with st.expander("✏️ Override Nilai (opsional)", expanded=False):
    cols = st.columns(4)
    keys1 = list("ABCDEFGHIJ")
    keys2 = list("KLMNOPQ")
    for i, k in enumerate(keys1):
        with cols[i % 4]:
            st.session_state.val_overrides[k] = st.text_input(f"{k} (override)", value=st.session_state.val_overrides.get(k, ""))
    st.markdown("---")
    for i, k in enumerate(keys2):
        with cols[i % 4]:
            st.session_state.val_overrides[k] = st.text_input(f"{k} (override)", value=st.session_state.val_overrides.get(k, ""))

# Tombol preview & download
pcol1, pcol2 = st.columns(2)
with pcol1:
    do_preview = st.button("🔁 Preview PDF (A–Q)", use_container_width=True)
with pcol2:
    do_download = st.button("⬇️ Download PDF (A–Q)", use_container_width=True)

def _items_from_state() -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    cs = st.session_state.coord_style
    ak = st.session_state.parsed_AK or {}

    # 1) A–E,J kiri (fixed). J kiri = (E-D+1), fallback J parse
    for k in ["A","B","C","D","E","J"]:
        style = cs[k]
        x, y = style["x"], style["y"]
        size, bold, align = style["size"], style["bold"], style["align"]
        if k == "J":
            val = day_diff_inclusive(ak.get("D"), ak.get("E"))
            if val is None or val <= 0:
                raw = ak.get("J")
                digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
                val = int(digits) if digits else ""
            text = str(val)
        else:
            text = get_value_for_key(k)
        if str(text).strip():
            items.append({"text": str(text), "x": x, "y": y, "size": size, "bold": bold, "from_right": False, "align": align})

    # 2) F–I editable (dari kiri). G/H/I rata tengah
    for k in ["F","G","H","I"]:
        style = cs[k]
        x, y = style["x"], style["y"]
        if x == 0 and y == 0:
            continue
        size, bold, align = style["size"], style["bold"], style["align"]
        txt = get_value_for_key(k).strip()
        if txt:
            items.append({"text": txt, "x": x, "y": y, "size": size, "bold": bold, "from_right": False, "align": align})

    # 3) K–Q kanan (X dari kanan + rata kanan). Q sekarang editable via panel.
    for k in ["K","L","M","N","O","P","Q"]:
        style = cs[k]
        x, y = style["x"], style["y"]
        size, bold, fr, align = style["size"], style["bold"], style["from_right"], style["align"]
        if x == 0 and y == 0 and not style.get("locked", False):
            continue
        txt = get_value_for_key(k).strip()
        if txt:
            items.append({"text": txt, "x": x, "y": y, "size": size, "bold": bold, "from_right": fr, "align": align})

    # 4) Items tambahan: K_DUP (260,534) dan J_RIGHT (110,534)
    extras = st.session_state.extra_items
    # K_DUP
    kd = extras["K_DUP"]
    text_k = get_value_for_key(kd["key"]).strip()
    if text_k:
        items.append({"text": text_k, "x": kd["x"], "y": kd["y"], "size": kd["size"], "bold": kd["bold"], "from_right": kd["from_right"], "align": kd["align"]})
    # J_RIGHT (pakai J parse)
    jr = extras["J_RIGHT"]
    raw_j = (st.session_state.parsed_AK or {}).get("J")
    j_text = "".join(ch for ch in str(raw_j or "") if ch.isdigit())
    if j_text:
        items.append({"text": j_text, "x": jr["x"], "y": jr["y"], "size": jr["size"], "bold": jr["bold"], "from_right": jr["from_right"], "align": jr["align"]})

    return items

# Generate preview
if do_preview:
    if not st.session_state.bg_template_bytes:
        st.warning("Template PDF belum tersedia. Upload file atau letakkan di assets/spj_blank.pdf.")
    else:
        items = _items_from_state()
        if not items:
            st.warning("Belum ada koordinat yang diisi.")
        else:
            st.session_state.preview_pdf = build_pdf_multi(st.session_state.bg_template_bytes, items)

# Preview (Chrome-safe; pakai <embed>)
if st.session_state.preview_pdf:
    b64 = base64.b64encode(st.session_state.preview_pdf).decode("utf-8")
    html = f"""
    <div style="height: 920px; width: 100%; border: 1px solid #ddd;">
      data:application/pdf;base64,{b64}#toolbar=1&navpanes=0&statusbar=0&view=FitH
      <p style="padding:8px;font-family:sans-serif;">
        Jika PDF tidak tampil, Anda bisa
        data:application/pdf;base64,{b64}mengunduhnya di sini</a>.
      </p>
    </div>
    """
    components.html(html, height=940, scrolling=True)
else:
    st.info("Preview belum tersedia. Klik **🔁 Preview PDF (A–Q)** setelah parse & reimburse.")

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
