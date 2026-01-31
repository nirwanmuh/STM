import re
from bs4 import BeautifulSoup, NavigableString, Tag

def _clean(txt: str | None) -> str | None:
    if txt is None:
        return None
    # Hilangkan spasi ganda & whitespace ringan
    return " ".join(txt.replace("\xa0", " ").split()).strip() or None

def _text_after_label(soup: BeautifulSoup, label: str) -> str | None:
    """
    Cari <span> dengan teks 'label' lalu ambil teks setelahnya (biasanya text node setelah <br>).
    """
    span = soup.find("span", string=re.compile(rf"^{re.escape(label)}\b", re.I))
    if not span:
        return None

    node = span.next_sibling
    # Lewati <br/> atau whitespace
    while node and (
        (isinstance(node, NavigableString) and not str(node).strip())
        or (isinstance(node, Tag) and node.name == "br")
    ):
        node = node.next_sibling

    if node is None:
        return None

    if isinstance(node, NavigableString):
        return _clean(str(node))
    elif isinstance(node, Tag):
        return _clean(node.get_text(separator=" ", strip=True))
    return None

def _h5_suffix_value(soup: BeautifulSoup, prefix: str) -> str | None:
    """
    Ambil nilai dari <h5> yang formatnya seperti 'Trip From : Jakarta'
    """
    h5 = soup.find("h5", string=re.compile(rf"^{re.escape(prefix)}\s*:\s*", re.I))
    if not h5:
        return None
    # Ambil bagian setelah titik dua
    m = re.search(r":\s*(.+)$", h5.get_text(" ", strip=True))
    return _clean(m.group(1)) if m else None

def _employee_name_from_top_right(soup: BeautifulSoup) -> str | None:
    h4 = soup.find("h4", string=re.compile(r"Employee Name", re.I))
    if not h4:
        # fallback: cari <span key="t-dt-employee-name">…</span> : Nama
        span = soup.find("span", attrs={"key": "t-dt-employee-name"})
        if span and span.parent and span.parent.name == "h4":
            text = span.parent.get_text(" ", strip=True)
            m = re.search(r":\s*(.+)$", text)
            return _clean(m.group(1)) if m else None
        return None
    text = h4.get_text(" ", strip=True)
    m = re.search(r":\s*(.+)$", text)
    return _clean(m.group(1)) if m else None

def _purpose_from_first_table(soup: BeautifulSoup) -> str | None:
    """
    Cari tabel yang header-nya mengandung 'Purpose', ambil sel pertama pada <tbody>.
    """
    tables = soup.find_all("table")
    for t in tables:
        ths = [th.get_text(" ", strip=True).lower() for th in t.find_all("th")]
        if any("purpose" in th for th in ths):
            first_td = t.find("tbody")
            if first_td:
                first_row = first_td.find("tr")
                if first_row:
                    td = first_row.find_all("td")
                    if td:
                        return _clean(td[0].get_text(" ", strip=True))
    return None

def _position_from_activity_table(soup: BeautifulSoup) -> str | None:
    """
    Cari tabel yang header-nya persis: Activity | Organization | Grade | Position
    Ambil sel 'Position' pada baris pertama.
    """
    tables = soup.find_all("table")
    for t in tables:
        ths = [th.get_text(" ", strip=True).lower() for th in t.find_all("th")]
        if {"activity", "organization", "grade", "position"}.issubset(set(ths)):
            tbody = t.find("tbody")
            if not tbody:
                continue
            row = tbody.find("tr")
            if not row:
                continue
            tds = row.find_all("td")
            if len(tds) >= 4:
                return _clean(tds[3].get_text(" ", strip=True))
    return None

def _last_approved_role_and_name_from_history(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """
    Dari modal #approvalHistoryModal, ambil item dengan ikon 'bx-badge-check' (approved) terakhir.
    Ambil <h5> sebagai role, <span class="text-muted"> sebagai nama.
    """
    modal = soup.find(id="approvalHistoryModal")
    if not modal:
        return (None, None)
    items = modal.select("ul.verti-timeline li.event-list")
    approved = []
    for li in items:
        icon = li.find("i", class_=re.compile(r"\bbx-badge-check\b"))
        if icon:
            approved.append(li)
    if not approved:
        return (None, None)
    last = approved[-1]
    role = last.find("h5")
    name = last.find("span", class_=re.compile(r"\btext-muted\b"))
    return (_clean(role.get_text(" ", strip=True)) if role else None,
            _clean(name.get_text(" ", strip=True)) if name else None)

def _daily_allowance_row(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """
    Temukan baris 'Daily Allowance' pada tabel transaksi:
    - Ambil '(3 Day)' -> 3
    - Ambil kolom 'Total' (IDR …)
    """
    rows = soup.find_all("tr")
    for tr in rows:
        tds = tr.find_all("td")
        if not tds:
            continue
        first = tds[0].get_text(" ", strip=True).lower()
        if "daily allowance" in first:
            # kolom ketiga berisi tanggal + (x Day)
            days_text = tds[2].get_text(" ", strip=True) if len(tds) >= 3 else ""
            m = re.search(r"\((\d+)\s*Day", days_text, re.I)
            days = m.group(1) if m else None
            total = tds[-1].get_text(" ", strip=True) if tds else None
            return (_clean(days), _clean(total))
    return (None, None)

def parse_html_to_A_to_K(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    A = _employee_name_from_top_right(soup)
    B = _h5_suffix_value(soup, "Trip From")
    C = _h5_suffix_value(soup, "Trip To")
    D = _text_after_label(soup, "Depart Date")
    E = _text_after_label(soup, "Return Date")
    F = _purpose_from_first_table(soup)
    G = _position_from_activity_table(soup)
    H, I = _last_approved_role_and_name_from_history(soup)
    J, K = _daily_allowance_row(soup)

    return {
        "A": A,
        "B": B,
        "C": C,
        "D": D,
        "E": E,
        "F": F,
        "G": G,
        "H": H,
        "I": I,
        "J": J,
        "K": K,
    }
