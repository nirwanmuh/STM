import streamlit as st
from src.parser import parse_html_to_A_to_K
import json

st.set_page_config(page_title="Trip HTML Parser (A–K)", page_icon="🧭", layout="wide")

st.title("🧭 Trip HTML Parser (A–K)")
st.caption("Tempel/unggah HTML Trip Detail, lalu aplikasi akan mengekstrak nilai A–K.")

with st.expander("Cara pakai", expanded=True):
    st.markdown(
        """
1) **Tempel** HTML di textarea **atau** **unggah** file HTML.  
2) Klik **Parse HTML**.  
3) Lihat hasil A–K, unduh JSON jika perlu.  
        """
    )

tab1, tab2 = st.tabs(["📄 Tempel HTML", "📤 Unggah File HTML"])
html_text = ""

with tab1:
    html_text = st.text_area(
        "Tempel HTML kamu di sini",
        height=420,
        placeholder="Tempel seluruh HTML Trip Detail di sini...",
    )

with tab2:
    uploaded = st.file_uploader("Unggah file .html", type=["html", "htm"])
    if uploaded is not None:
        html_text = uploaded.read().decode("utf-8", errors="ignore")

parse_btn = st.button("🔎 Parse HTML", type="primary", use_container_width=True)

if parse_btn:
    if not html_text.strip():
        st.error("Silakan tempel atau unggah HTML terlebih dahulu.")
        st.stop()

    data = parse_html_to_A_to_K(html_text)

    st.subheader("Hasil Ekstraksi A–K")
    cols = st.columns(2)
    with cols[0]:
        st.write("**A** – Employee Name:", data.get("A"))
        st.write("**B** – Trip From:", data.get("B"))
        st.write("**C** – Trip To:", data.get("C"))
        st.write("**D** – Depart Date:", data.get("D"))
        st.write("**E** – Return Date:", data.get("E"))
    with cols[1]:
        st.write("**F** – Purpose:", data.get("F"))
        st.write("**G** – Position:", data.get("G"))
        st.write("**H** – Last Approved Role:", data.get("H"))
        st.write("**I** – Last Approved By:", data.get("I"))
        st.write("**J** – Daily Allowance (Days):", data.get("J"))
        st.write("**K** – Daily Allowance Total:", data.get("K"))

    st.divider()
    st.subheader("JSON")
    st.code(json.dumps(data, ensure_ascii=False, indent=2), language="json")

    st.download_button(
        "💾 Unduh JSON",
        data=json.dumps(data, ensure_ascii=False, indent=2),
        file_name="trip_ak.json",
        mime="application/json",
        use_container_width=True,
    )
