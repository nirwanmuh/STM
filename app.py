import json
import os
import io
import base64
from typing import List, Dict, Optional

import streamlit as st
import streamlit.components.v1 as components

from src.parser import parse_html_to_A_to_K


# =========================
# Konfigurasi UI (dev toggle)
# =========================
# Secara default, sembunyikan menu overlay PDF, status template, dan pengaturan koordinat.
# Jika perlu debug/develop, set env: SHOW_OVERLAY_UI=1 atau di runtime:
# st.session_state["SHOW_OVERLAY_UI"] = True
SHOW_OVERLAY_UI_DEFAULT = False
SHOW_OVERLAY_UI = bool(int(os.getenv("SHOW_OVERLAY_UI", "1" if SHOW_OVERLAY_UI_DEFAULT else "0")))
SHOW_OVERLAY_UI = st.session_state.get("SHOW_OVERLAY_UI", SHOW_OVERLAY_UI)


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
    """Hitung (E - D + 1) hari (inklusif): 19..21 -> 3."""
    d1 = parse_date_or_none(D)
    d2 = parse_date_or_none(E)
    if not d1 or not d2:
        return None
    return (d2.date() - d1.date()).days + 1


def today_id_str(prefix_city: str = "Jakarta") -> str:
    """
    "Jakarta, 2 Februari 2026" — format tanggal Indonesia dengan zona Asia/Jakarta jika tersedia.
    Menggunakan zoneinfo (Python 3.9+). Jika tidak ada, fallback ke datetime.now() lokal.
    """
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo  # Python 3.9+
        now = datetime.now(ZoneInfo("Asia/Jakarta"))
    except Exception:
        now = datetime.now()

    bulan_id = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember"
    ]
    d = now.day
    m = bulan_id[now.month - 1]
    y = now.year
    return f"{prefix_city}, {d} {m} {y}"


# =========================
# Terbilang (Indonesia) untuk Rupiah
# =========================
def _terbilang_lt_1000(n: int) -> str:
    """Terbilang untuk 0..999 (bahasa Indonesia)."""
    assert 0 <= n < 1000
    satuan = ["", "satu", "dua", "tiga", "empat", "lima",
              "enam", "tujuh", "delapan", "sembilan"]

    if n == 0:
        return ""
    if n < 10:
        return satuan[n]
    if n < 20:
        if n == 10:
            return "sepuluh"
        if n == 11:
            return "sebelas"
        return f"{satuan[n-10]} belas"
    if n < 100:
        puluh = n // 10
        sisa = n % 10
        bagian = f"{satuan[puluh]} puluh"
        if sisa:
            bagian += f" {satuan[sisa]}"
        return bagian
    # 100..999
    ratus = n // 100
    sisa = n % 100
    if ratus == 1:
        bagian = "seratus"
    else:
        bagian = f"{satuan[ratus]} ratus"
    if sisa:
        bagian += f" {_terbilang_lt_1000(sisa)}"
    return bagian


def terbilang_id(n: int) -> str:
    """Terbilang angka non-negatif (tanpa 'rupiah')."""
    if n == 0:
        return "nol"
    if n < 0:
        return f"minus {terbilang_id(-n)}"

    bagian = []
    scales = [
        (1_000_000_000_000, "triliun"),
        (1_000_000_000, "miliar"),
        (1_000_000, "juta"),
        (1000, "ribu"),
        (1, ""),
    ]
    sisa = n
    for skala, nama in scales:
        if sisa >= skala:
            hitung = sisa // skala
            sisa = sisa % skala
            if skala == 1000 and hitung == 1:
                bagian.append("seribu")
            else:
                if hitung < 1000:
                    kata = _terbilang_lt_1000(hitung)
                else:
                    kata = terbilang_id(hitung)
                if kata:
                    if nama:
                        bagian.append(f"{kata} {nama}")
                    else:
                        bagian.append(kata)
    return " ".join(bagian).strip()


def terbilang_rupiah(n: int) -> str:
    """Terbilang + akhiran 'rupiah'."""
    return f"{terbilang_id(n)} rupiah"


# =========================
# State init
# =========================
def ensure_states():
    if "parsed_AK" not in st.session_state:
        st.session_state.parsed_AK: Dict[str, str | None] = {}
    if "reimburse_rows" not in st.session_state:
        st.session_state.reimburse_rows: List[Dict] = []
    if "totals_LQ" not in st.session_state:
        st.session_state.totals_LQ: Dict[str, int] = {k: 0 for k in list("LMNOPQ")}
    # PDF templates & preview
    if "bg_template_bytes" not in st.session_state:
        st.session_state.bg_template_bytes: Optional[bytes] = None
    if "bg_template2_bytes" not in st.session_state:
        st.session_state.bg_template2_bytes: Optional[bytes] = None
    if "preview_pdf" not in st.session_state:
        st.session_state.preview_pdf: Optional[bytes] = None
    # Override nilai (opsional)
    if "val_overrides" not in st.session_state:
        st.session_state.val_overrides: Dict[str, str] = {}

    # Koordinat HALAMAN 1 (fixed)
    if "coord_style" not in st.session_state:
        st.session_state.coord_style = {
            "A": {"x": 190.0, "y": 666.0, "size": 9, "bold": False, "underline": False, "fmt": "raw", "from_right": False, "align": "left", "locked": True},
            "B": {"x": 190.0, "y": 652.5, "size": 9, "bold": False, "underline": False, "fmt": "raw", "from_right": False, "align": "left", "locked": True},
            "C": {"x": 190.0, "y": 639.0, "size": 9, "bold": False, "underline": False, "fmt": "raw", "from_right": False, "align": "left", "locked": True},
            "D": {"x": 190.0, "y": 625.5, "size": 9, "bold": False, "underline": False, "fmt": "raw", "from_right": False, "align": "left", "locked": True},
            "E": {"x": 190.0, "y": 612.0, "size": 9, "bold": False, "underline": False, "fmt": "raw", "from_right": False, "align": "left", "locked": True},
            "J": {"x": 190.0, "y": 600.0, "size": 9, "bold": False, "underline": False, "fmt": "raw", "from_right": False, "align": "left", "locked": True},

            "F": {"x": 0.0, "y": 0.0, "size": 10, "bold": False, "underline": False, "fmt": "raw", "from_right": False, "align": "left", "locked": False},
            "G": {"x": 439.0, "y": 78.0, "size": 7, "bold": False, "underline": False, "fmt": "raw", "from_right": False, "align": "center", "locked": True, "max_width": 135.0},
            "H": {"x": 124.0, "y": 78.0, "size": 7, "bold": False, "underline": False, "fmt": "raw", "from_right": False, "align": "center", "locked": True, "max_width": 135.0},
            "I": {"x": 124.0, "y": 88.0, "size": 8, "bold": True, "underline": True, "fmt": "raw", "from_right": False, "align": "center", "locked": True},

            "K": {"x": 260.0, "y": 520.0, "size": 9, "bold": False, "underline": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "L": {"x": 260.0, "y": 313.0, "size": 9, "bold": False, "underline": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "M": {"x": 260.0, "y": 299.0, "size": 9, "bold": False, "underline": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "N": {"x": 260.0, "y": 286.0, "size": 9, "bold": False, "underline": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "O": {"x": 260.0, "y": 273.0, "size": 9, "bold": False, "underline": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "P": {"x": 260.0, "y": 260.0, "size": 9, "bold": False, "underline": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},
            "Q": {"x": 260.0, "y": 227.0, "size": 9, "bold": True, "underline": False, "fmt": "number", "from_right": True, "align": "right", "locked": True},

            "R": {"x": 281.0, "y": 88.0, "size": 8, "bold": True, "underline": True, "fmt": "raw", "from_right": False, "align": "center", "locked": True},
            "S": {"x": 281.0, "y": 78.0, "size": 7, "bold": False, "underline": False, "fmt": "raw", "from_right": False, "align": "center", "locked": True, "max_width": 135.0},
        }

    # Item duplikasi — halaman 1
    if "extra_items" not in st.session_state:
        st.session_state.extra_items = {
            "K_DUP": {"key": "K", "x": 260.0, "y": 534.0, "size": 9, "bold": False, "underline": False, "from_right": True, "align": "right"},
            "J_RIGHT": {"key": "J", "x": 120.0, "y": 534.0, "size": 9, "bold": False, "underline": False, "from_right": True, "align": "right"},
            "A_DUP": {"key": "A", "x": 439.0, "y": 88.0, "size": 8, "bold": True, "underline": True, "from_right": False, "align": "center"},
            "Q_DUP": {"key": "Q", "x": 260.0, "y": 183.0, "size": 9, "bold": True, "underline": False, "from_right": True, "align": "right"},
        }

    # Koordinat HALAMAN 2 — EDITABLE (A2..Q2 + Q2_TB + DESC2 + R2 + S2 + CUSTOM)
    if "coord_style_page2" not in st.session_state:
        cs2 = {}

        # A2 / G2
        cs2["A2"] = {"x": 167.0, "y": 653.0, "size": 9, "bold": False, "underline": False, "align": "left", "from_right": False, "max_width": 0.0}
        cs2["G2"] = {"x": 167.0, "y": 641.0, "size": 9, "bold": False, "underline": False, "align": "left", "from_right": False, "max_width": 0.0}

        # K2..Q2 angka (right-anchored)
        def _right_num(x, y, size=9, bold=False):
            return {"x": float(x), "y": float(y), "size": int(size), "bold": bool(bold),
                    "underline": False, "align": "right", "from_right": True, "max_width": 0.0}

        cs2["K2"] = _right_num(118, 432)
        cs2["L2"] = _right_num(118, 482.5)
        cs2["M2"] = _right_num(118, 495)
        cs2["N2"] = _right_num(118, 470)
        cs2["O2"] = _right_num(118, 457.5)
        cs2["P2"] = _right_num(118, 445)
        cs2["Q2"] = _right_num(118, 420)  # Q2 = angka (Q+K)

        # Q2_TB = terbilang (Q+K) — default x133,y407, max_width 350
        cs2["Q2_TB"] = {"x": 133.0, "y": 407.0, "size": 9, "bold": False, "underline": False,
                        "align": "left", "from_right": False, "max_width": 350.0}

        # DESC2 = kalimat keterangan C/D/E/F — SET agar langsung tercetak
        cs2["DESC2"] = {"x": 82.0, "y": 370.0, "size": 9, "bold": False, "underline": False,
                        "align": "left", "from_right": False, "max_width": 420.0}

        # R2 / S2 (opsional)
        cs2["R2"] = {"x": 0.0, "y": 0.0, "size": 8, "bold": True, "underline": True, "align": "center", "from_right": False, "max_width": 0.0}
        cs2["S2"] = {"x": 0.0, "y": 0.0, "size": 7, "bold": False, "underline": False, "align": "center", "from_right": False, "max_width": 135.0}

        # ===== Tambahan custom =====
        cs2["CITY_TODAY"] = {
            "x": 180.0, "y": 300.0, "size": 9, "bold": False, "underline": False,
            "align": "center", "from_right": True, "max_width": 0.0
        }
        cs2["A2_AGAIN"] = {
            "x": 180.0, "y": 225.0, "size": 9, "bold": True, "underline": True,
            "align": "center", "from_right": True, "max_width": 0.0
        }
        cs2["G2_AGAIN"] = {
            "x": 180.0, "y": 212.0, "size": 9, "bold": False, "underline": False,
            "align": "center", "from_right": True, "max_width": 135.0
        }

        # === NIK di halaman 2 (disimpan; UI edit disembunyikan) ===
        cs2["NIK2"] = {
            "x": 167.0, "y": 628.0,
            "size": 9,
            "bold": False,
            "underline": False,
            "align": "left",
            "from_right": False,
            "max_width": 0.0
        }

        st.session_state.coord_style_page2 = cs2

    # Lock editor halaman 2 (tetap disembunyikan di UI umum)
    st.session_state["lock_page2_coords"] = True  # force hide editor


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


def get_numeric_value_for_key(key: str) -> int:
    """Ambil nilai angka murni untuk key."""
    ak = st.session_state.parsed_AK or {}
    lq = st.session_state.totals_LQ or {}

    if key == "K":
        return idr_to_int(ak.get("K"))
    if key in list("LMNOPQ"):
        try:
            return int(lq.get(key, 0))
        except Exception:
            return 0
    raw = ak.get(key, "")
    try:
        return idr_to_int(str(raw))
    except Exception:
        return 0


def get_value_for_key(key: str) -> str:
    """Ambil nilai final untuk key A..Q + formatting per 'fmt' (0 -> '-')."""
    ov = st.session_state.val_overrides.get(key)
    if ov not in (None, ""):
        if ov.strip().isdigit() and int(ov.strip()) == 0:
            return "-"
        return str(ov)

    ak = st.session_state.parsed_AK or {}
    lq = st.session_state.totals_LQ or {}

    if key in list("ABCDEFGHIJKRS"):
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
            val = idr_to_int(raw) if isinstance(raw, str) else int(raw)
        except Exception:
            val = 0
        return "-" if val == 0 else fmt_n(int(val))

    if fmt_mode == "auto":
        try:
            val = idr_to_int(raw) if isinstance(raw, str) else int(raw)
            return "-" if val == 0 else fmt_n(int(val))
        except Exception:
            pass
        return str(raw or "")

    return str(raw or "")


# =========================
# PDF rendering utils
# =========================
def _render_one_page(background_pdf_bytes: bytes, items: List[Dict[str, object]]) -> bytes:
    """Render satu halaman overlay + merge dengan background."""
    if not background_pdf_bytes:
        return b""

    try:
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase.pdfmetrics import stringWidth
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

    def wrap_text_by_space(text: str, font_name: str, font_size: float, max_width: float) -> List[str]:
        """Bungkus teks per spasi agar tiap baris <= max_width."""
        words = text.split()
        if not words:
            return []
        lines: List[str] = []
        current = ""

        def w(s: str) -> float:
            from reportlab.pdfbase.pdfmetrics import stringWidth
            return stringWidth(s, font_name, font_size)

        for word in words:
            candidate = word if not current else f"{current} {word}"
            if w(candidate) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                    current = word
                    while w(current) > max_width and len(current) > 1:
                        cut = len(current)
                        while cut > 1 and w(current[:cut]) > max_width:
                            cut -= 1
                        lines.append(current[:cut])
                        current = current[cut:]
                else:
                    tmp = word
                    while w(tmp) > max_width and len(tmp) > 1:
                        cut = len(tmp)
                        while cut > 1 and w(tmp[:cut]) > max_width:
                            cut -= 1
                        lines.append(tmp[:cut])
                        tmp = tmp[cut:]
                    current = tmp
        if current:
            lines.append(current)
        return lines

    def draw_underlined_text(text: str, x_anchor: float, y: float, align: str, font_name: str, font_size: float):
        """Garis underline di bawah teks sesuai alignment."""
        from reportlab.pdfbase.pdfmetrics import stringWidth
        width = stringWidth(text, font_name, font_size)
        if align == "right":
            x0 = x_anchor - width
        elif align == "center":
            x0 = x_anchor - width / 2.0
        else:
            x0 = x_anchor
        y_line = y - max(1.0, font_size * 0.15)
        c.setLineWidth(0.6)
        c.line(x0, y_line, x0 + width, y_line)

    for it in items:
        text = str(it.get("text") or "").strip()
        if not text:
            continue

        x_in = float(it.get("x", 0))  # untuk from_right=True, ini jarak dari sisi kanan
        y = float(it.get("y", 0))
        size = int(it.get("size", 10))
        bold = bool(it.get("bold", False))
        underline = bool(it.get("underline", False))
        from_right = bool(it.get("from_right", False))
        align = (it.get("align") or "left").lower()
        max_width = float(it.get("max_width", 0.0))

        font = "Helvetica-Bold" if bold else "Helvetica"
        try:
            c.setFont(font, size)
        except Exception:
            c.setFont("Helvetica", 10)
            font = "Helvetica"
            size = 10

        # Anchor X
        x_anchor = (page_w - x_in) if from_right else x_in

        # Wrapping generic
        if max_width > 0:
            lines = wrap_text_by_space(text, font, size, max_width)
            line_height = size * 1.2
            y_cursor = y
            for ln in lines:
                if align == "right":
                    c.drawRightString(x_anchor, y_cursor, ln)
                    if underline:
                        draw_underlined_text(ln, x_anchor, y_cursor, "right", font, size)
                elif align == "center":
                    c.drawCentredString(x_anchor, y_cursor, ln)
                    if underline:
                        draw_underlined_text(ln, x_anchor, y_cursor, "center", font, size)
                else:
                    c.drawString(x_anchor, y_cursor, ln)
                    if underline:
                        draw_underlined_text(ln, x_anchor, y_cursor, "left", font, size)
                y_cursor -= line_height
        else:
            if align == "right":
                c.drawRightString(x_anchor, y, text)
            elif align == "center":
                c.drawCentredString(x_anchor, y, text)
            else:
                c.drawString(x_anchor, y, text)
            if underline:
                draw_underlined_text(text, x_anchor, y, align, font, size)

    c.showPage()
    c.save()
    overlay_pdf = buf.getvalue()

    # Merge overlay ke base
    try:
        from PyPDF2 import PdfReader, PdfWriter
        overlay_reader = PdfReader(io.BytesIO(overlay_pdf))
        overlay_page = overlay_reader.pages[0]
        base_page.merge_page(overlay_page)  # pypdf >= 3
    except Exception:
        try:
            base_page.mergePage(overlay_page)  # legacy
        except Exception as e:
            st.error(f"Gagal merge overlay: {e}")
            return overlay_pdf

    writer = PdfWriter()
    writer.add_page(base_page)
    out_buf = io.BytesIO()
    writer.write(out_buf)
    return out_buf.getvalue()


def build_pdf_multi_pages(background_pages: List[bytes], items_per_page: List[List[Dict[str, object]]]) -> bytes:
    """Render tiap halaman dan gabungkan ke satu PDF."""
    from PyPDF2 import PdfReader, PdfWriter
    writer = PdfWriter()
    any_page = False
    for idx, bg in enumerate(background_pages):
        if not bg:
            continue
        items = items_per_page[idx] if idx < len(items_per_page) else []
        page_pdf = _render_one_page(bg, items)
        try:
            reader = PdfReader(io.BytesIO(page_pdf))
            page = reader.pages[0]
            writer.add_page(page)
            any_page = True
        except Exception as e:
            st.error(f"Gagal merakit halaman #{idx+1}: {e}")

    if not any_page:
        return b""

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# =========================
# UI
# =========================
st.set_page_config(page_title="STM Generator", page_icon="🧭", layout="wide")
ensure_states()

st.title("STM Generator")
st.caption("Web Untuk Generate Formulir SPJ")

with st.expander("Cara pakai (singkat)", expanded=False):
    st.markdown(
        "- **Langkah 1**: Paste/Unggah HTML, klik **Parse HTML** \n"
        "- **Langkah 2**: Buka **Data Atasan** dan **Reimburse** (Opsional), isi datanya.\n"
        "- **Langkah 3**: Klik **Generate PDF** lalu **Download**."
    )

# ===== Input HTML =====
tab1, tab2 = st.tabs(["📄 Tempel HTML", "📤 Unggah File HTML"])
html_text = ""

with tab1:
    html_text_input = st.text_area(
        "Tempel HTML kamu di sini",
        height=300,
        placeholder="Tempel seluruh HTML Trip Detail di sini...",
    )
    if html_text_input:
        html_text = html_text_input

with tab2:
    uploaded = st.file_uploader("Unggah file .html", type=["html", "htm"])
    if uploaded is not None:
        html_text = uploaded.read().decode("utf-8", errors="ignore")

parse_btn = st.button("🔎 Parse HTML", type="primary", use_container_width=True, key="btn_parse_html")

# ===== Parse A–K =====
if parse_btn:
    if not html_text or not html_text.strip():
        st.error("Silakan tempel atau unggah HTML terlebih dahulu.")
        st.stop()
    old_r = (st.session_state.parsed_AK or {}).get("R")
    old_s = (st.session_state.parsed_AK or {}).get("S")
    old_nik = (st.session_state.parsed_AK or {}).get("NIK")  # pertahankan NIK
    st.session_state.parsed_AK = parse_html_to_A_to_K(html_text)
    if old_r:
        st.session_state.parsed_AK["R"] = old_r
    if old_s:
        st.session_state.parsed_AK["S"] = old_s
    if old_nik:
        st.session_state.parsed_AK["NIK"] = old_nik
    st.success("HTML berhasil diparse.")

# ===== Data Atasan (R & S) — collapsible =====
with st.expander("👤 Data Atasan (Opsional)", expanded=False):
    with st.form("atasan_form", clear_on_submit=False):
        r_input = st.text_input("Nama atasan", value=(st.session_state.parsed_AK.get("R") or ""), placeholder="nama atasan")
        s_input = st.text_input("Jabatan atasan", value=(st.session_state.parsed_AK.get("S") or ""), placeholder="jabatan atasan")
        submit_rs = st.form_submit_button("💾 Simpan Atasan", use_container_width=True)
        if submit_rs:
            st.session_state.parsed_AK["R"] = r_input.strip()
            st.session_state.parsed_AK["S"] = s_input.strip()
            st.success("Data atasan disimpan (R & S).")

# ===== Data Karyawan (NIK) — collapsible =====
with st.expander("🪪 Data Karyawan (NIK)", expanded=False):
    with st.form("nik_form", clear_on_submit=False):
        nik_old = (st.session_state.parsed_AK or {}).get("NIK") or ""
        nik_input = st.text_input(
            "NIK",
            value=nik_old,
            placeholder="contoh: 3174xxxxxxxxxxxx",
            help="Angka saja; karakter non-digit akan dibersihkan otomatis saat render."
        )
        submit_nik = st.form_submit_button("💾 Simpan NIK", use_container_width=True)
        if submit_nik:
            st.session_state.parsed_AK["NIK"] = nik_input.strip()
            st.success("NIK disimpan.")

# ===== Reimburse — collapsible =====
with st.expander("🧾 Reimburse (Opsional)", expanded=False):
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
                st.rerun()

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

# (DISembunyikan) Hasil Ekstraksi A–K dan JSON A–Q
# — permintaanmu: hide menu hasil ekstraksi & JSON, jadi tidak ditampilkan.

# =========================
# Template PDF (auto-load, UI overlay disembunyikan)
# =========================
DEFAULT_BG_PATH = os.environ.get("SPJ_BG_PATH", "assets/spj_blank.pdf")
if not st.session_state.bg_template_bytes:
    try:
        if os.path.exists(DEFAULT_BG_PATH):
            with open(DEFAULT_BG_PATH, "rb") as f:
                st.session_state.bg_template_bytes = f.read()
    except Exception as e:
        pass

DEFAULT_BG2_PATH = os.environ.get("SPJ_BG2_PATH", "assets/spj_blank2.pdf")
if not st.session_state.bg_template2_bytes:
    try:
        if os.path.exists(DEFAULT_BG2_PATH):
            with open(DEFAULT_BG2_PATH, "rb") as f:
                st.session_state.bg_template2_bytes = f.read()
        else:
            fallback = "assets/spj_blank2"
            if os.path.exists(fallback):
                with open(fallback, "rb") as f:
                    st.session_state.bg_template2_bytes = f.read()
    except Exception as e:
        pass

# =========================
# Items builders
# =========================
def _items_page1_from_state() -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    cs = st.session_state.coord_style
    ak = st.session_state.parsed_AK or {}

    # 1) A–E, J kiri
    for k in ["A", "B", "C", "D", "E", "J"]:
        style = cs[k]
        x, y = style["x"], style["y"]
        size, bold, align, ul = style["size"], style["bold"], style["align"], style["underline"]

        if k == "J":
            val = day_diff_inclusive(ak.get("D"), ak.get("E"))
            if val is None or val <= 0:
                raw = ak.get("J")
                digits = "".join(ch for ch in str(raw or "") if ch.isdigit())
                val = int(digits) if digits else ""
            text = "-" if (isinstance(val, int) and val == 0) or str(val).strip() == "" else str(val)

        elif k == "A":
            base_a = (get_value_for_key("A") or "").strip()
            raw_nik = (st.session_state.parsed_AK or {}).get("NIK", "")
            digits = "".join(ch for ch in str(raw_nik) if ch.isdigit())
            nik_text = digits or str(raw_nik).strip()
            if base_a or nik_text:
                text = f"value a: {base_a}"
                if nik_text:
                    text += f" + ({nik_text})"
            else:
                text = ""  # keduanya kosong: jangan cetak apa-apa

        else:
            text = get_value_for_key(k)

        if str(text).strip():
            items.append({
                "key": k,
                "text": str(text),
                "x": x,
                "y": y,
                "size": size,
                "bold": bold,
                "underline": ul,
                "from_right": False,
                "align": align
            })

    # 2) F–I
    for k in ["F", "G", "H", "I"]:
        style = cs[k]
        x, y = style["x"], style["y"]
        size, bold, fr, align, ul = style["size"], style["bold"], style["from_right"], style["align"], style["underline"]
        txt = get_value_for_key(k).strip()
        if k == "F" and (x == 0 and y == 0):
            continue
        if txt:
            item = {"key": k, "text": txt, "x": x, "y": y, "size": size, "bold": bold, "underline": ul, "from_right": fr, "align": align}
            if k in ["G", "H"]:
                item["max_width"] = float(style.get("max_width", 135.0))
            items.append(item)

    # 2b) R & S
    r_style = cs["R"]; r_txt = (ak.get("R") or "").strip()
    if r_txt:
        items.append({"key": "R", "text": r_txt, "x": r_style["x"], "y": r_style["y"], "size": r_style["size"], "bold": r_style["bold"], "underline": r_style["underline"], "from_right": r_style["from_right"], "align": r_style["align"]})
    s_style = cs["S"]; s_txt = (ak.get("S") or "").strip()
    if s_txt:
        items.append({"key": "S", "text": s_txt, "x": s_style["x"], "y": s_style["y"], "size": s_style["size"], "bold": s_style["bold"], "underline": s_style["underline"], "from_right": s_style["from_right"], "align": s_style["align"], "max_width": float(s_style.get("max_width", 135.0))})

    # 3) K–Q kanan
    for k in ["K", "L", "M", "N", "O", "P", "Q"]:
        style = cs[k]
        x, y = style["x"], style["y"]
        size, bold, fr, align, ul = style["size"], style["bold"], style["from_right"], style["align"], style["underline"]
        txt = get_value_for_key(k).strip()
        if txt:
            items.append({"key": k, "text": txt, "x": x, "y": y, "size": size, "bold": bold, "underline": ul, "from_right": fr, "align": align})

    # 4) Extra: K_DUP, J_RIGHT, A_DUP, Q_DUP (Q + K)
    extras = st.session_state.extra_items

    kd = extras["K_DUP"]; text_k = get_value_for_key(kd["key"]).strip()
    if text_k:
        items.append({"key": kd["key"], "text": text_k, "x": kd["x"], "y": kd["y"], "size": kd["size"], "bold": kd["bold"], "underline": kd["underline"], "from_right": kd["from_right"], "align": kd["align"]})

    jr = extras["J_RIGHT"]; raw_j = (st.session_state.parsed_AK or {}).get("J")
    j_digits = "".join(ch for ch in str(raw_j or "") if ch.isdigit())
    j_text = "-" if (j_digits == "" or int(j_digits) == 0) else j_digits
    if j_text:
        items.append({"key": jr["key"], "text": j_text, "x": jr["x"], "y": jr["y"], "size": jr["size"], "bold": jr["bold"], "underline": jr["underline"], "from_right": jr["from_right"], "align": jr["align"]})

    ad = extras["A_DUP"]; a_text = get_value_for_key(ad["key"]).strip()
    if a_text:
        items.append({"key": ad["key"], "text": a_text, "x": ad["x"], "y": ad["y"], "size": ad["size"], "bold": ad["bold"], "underline": ad["underline"], "from_right": ad["from_right"], "align": ad["align"]})

    qd = extras["Q_DUP"]; q_num = get_numeric_value_for_key("Q"); k_num = get_numeric_value_for_key("K")
    sum_qk = int(q_num) + int(k_num)
    qd_text = "-" if sum_qk == 0 else fmt_n(sum_qk)
    items.append({"key": qd["key"], "text": qd_text, "x": qd["x"], "y": qd["y"], "size": qd["size"], "bold": qd["bold"], "underline": qd["underline"], "from_right": qd["from_right"], "align": qd["align"]})

    return items


def _items_page2_from_state() -> List[Dict[str, object]]:
    """
    Halaman 2:
    - Q2 = ANGKA (Q + K) -> "-" jika 0
    - Q2_TB = TERBILANG (Q + K) + " rupiah"
    - DESC2 = "Telah sesuai ... ke [C], tanggal [D] s/d [E] dalam rangka [F]."
    - CITY_TODAY = "Jakarta, [tanggal hari ini]"
    - A2_AGAIN = value A
    - G2_AGAIN = value G
    - NIK2 = value NIK (digits-only prefer), pos & style telah disimpan
    """
    items: List[Dict[str, object]] = []
    cs2 = st.session_state.coord_style_page2

    for key, style in cs2.items():
        x = float(style["x"]); y = float(style["y"])
        if x == 0.0 and y == 0.0:
            continue

        if key == "Q2":
            q_num = get_numeric_value_for_key("Q"); k_num = get_numeric_value_for_key("K")
            total = int(q_num) + int(k_num)
            text = "-" if total == 0 else fmt_n(total)
        elif key == "Q2_TB":
            q_num = get_numeric_value_for_key("Q"); k_num = get_numeric_value_for_key("K")
            total = int(q_num) + int(k_num)
            text = terbilang_rupiah(total) if total != 0 else "nol rupiah"
        elif key == "DESC2":
            C = (get_value_for_key("C") or "").strip()
            D = (get_value_for_key("D") or "").strip()
            E = (get_value_for_key("E") or "").strip()
            F = (get_value_for_key("F") or "").strip()
            text = f"Telah sesuai sebagaimana adanya digunakan dalam rangka keperluan perjalanan dinas ke {C}, tanggal {D} s/d {E} dalam rangka {F}."
            text = text.strip()
        elif key == "CITY_TODAY":
            text = today_id_str("Jakarta")
        elif key == "A2_AGAIN":
            text = (get_value_for_key("A") or "").strip()
        elif key == "G2_AGAIN":
            text = (get_value_for_key("G") or "").strip()
        elif key == "NIK2":
            # Ambil NIK dari parsed_AK; bersihkan ke digit-only saat render.
            raw_nik = (st.session_state.parsed_AK or {}).get("NIK", "")
            digits = "".join(ch for ch in str(raw_nik) if ch.isdigit())
            text = digits or (str(raw_nik).strip() if str(raw_nik).strip() else "")
        else:
            base_key = key[:-1].upper() if key.endswith("2") else key.upper()
            if base_key in list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
                text = get_value_for_key(base_key).strip()
            else:
                text = ""

        if not text:
            continue

        items.append({
            "key": key,
            "text": text,
            "x": x,
            "y": y,
            "size": int(style["size"]),
            "bold": bool(style["bold"]),
            "underline": bool(style["underline"]),
            "from_right": bool(style["from_right"]),
            "align": str(style["align"]),
            "max_width": float(style.get("max_width", 0.0)),
        })

    return items


# =========================
# Generate & Download — single flow
# =========================
st.divider()
st.subheader("📄 Generate & Download PDF")

btn_generate = st.button("⚙️ Generate PDF", use_container_width=True, key="btn_generate_pdf")

if btn_generate:
    bg1 = st.session_state.bg_template_bytes
    bg2 = st.session_state.bg_template2_bytes
    if not bg1 or not bg2:
        st.error("Template PDF belum tersedia. Pastikan file ada di `assets/spj_blank.pdf` dan `assets/spj_blank2.pdf`.")
    else:
        items1 = _items_page1_from_state()
        items2 = _items_page2_from_state()
        pdf_bytes = build_pdf_multi_pages([bg1, bg2], [items1, items2])
        if pdf_bytes:
            st.session_state.preview_pdf = pdf_bytes
            st.success("PDF berhasil digenerate. Silakan download.")
        else:
            st.warning("Gagal membuat PDF. Pastikan template & data sudah valid.")

if st.session_state.get("preview_pdf"):
    st.download_button(
        "⬇️ Download PDF",
        data=st.session_state.preview_pdf,
        file_name="SPJ_A_to_Q_overlay_2hal.pdf",
        mime="application/pdf",
        use_container_width=True,
        key="dl_pdf_single"
    )
``
