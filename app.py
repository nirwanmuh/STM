import json
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
