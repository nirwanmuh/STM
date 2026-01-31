import re
from bs4 import BeautifulSoup, NavigableString, Tag
from typing import Optional, Tuple, Dict

# ---------- Utilities ----------
def _clean(txt: Optional[str]) -> Optional[str]:
    if txt is None:
        return None
    return " ".join(txt.replace("\xa0", " ").split()).strip() or None

def _text_after_label(soup: BeautifulSoup, label: str) -> Optional[str]:
    """
    Cari <span> berisi 'label' (mis. 'Depart Date'), lalu ambil teks setelah <br>.
    """
    # Jangan pakai string=regex karena node sering punya anak; pakai lambda match di tag <span>.
    span = None
    for sp in soup.find_all("span"):
        if sp.get_text(strip=True).lower().startswith(label.lower()):
            span = sp
            break
    if not span:
        return None

    node = span.next_sibling
    while node and (
        (isinstance(node, NavigableString) and not str(node).strip()) or
        (isinstance(node, Tag) and node.name == "br")
    ):
        node = node.next_sibling

    if node is None:
        return None

    if isinstance(node, NavigableString):
        return _clean(str(node))
    if isinstance(node, Tag):
        return _clean(node.get_text(" ", strip=True))
    return None

def _h5_suffix_value(soup: BeautifulSoup, prefix: str) -> Optional[str]:
    """
    Ambil nilai dari <h5> yang format tampilannya seperti 'Trip From : Jakarta'
    CATATAN: <h5> berisi <i> ikon, jadi harus pakai get_text() bukan string=...
    """
    for h5 in soup.find_all("h5"):
        text = h5.get_text(" ", strip=True)
        if re.match(rf"^{re.escape(prefix)}\s*:", text, flags=re.I):
            m = re.search(r":\s*(.+)$", text)
            if m:
                return _clean(m.group(1))
    return None

def _employee_name_from_top_right(soup: BeautifulSoup) -> Optional[str]:
    # Pola umum: <h4><span>Employee Name</span> : Nama</h4>
    # Cari semua h4 lalu periksa teksnya
    for h4 in soup.find_all("h4"):
        t = h4.get_text(" ", strip=True)
        if re.search(r"\bEmployee Name\b", t, flags=re.I):
            m = re.search(r":\s*(.+)$", t)
            if m:
                return _clean(m.group(1))
    # Fallback (semestinya tidak kepakai, tapi aman):
    span = soup.find("span", attrs={"key": "t-dt-employee-name"})
    if span and span.parent and span.parent.name == "h4":
        text = span.parent.get_text(" ", strip=True)
        m = re.search(r":\s*(.+)$", text)
        return _clean(m.group(1)) if m else None
    return None

def _purpose_from_first_table(soup: BeautifulSoup) -> Optional[str]:
    """
    Cari tabel yang header-nya mengandung 'Purpose', ambil sel pertama <tbody>.
    """
    for t in soup.find_all("table"):
        ths = [th.get_text(" ", strip=True).lower() for th in t.find_all("th")]
        if any("purpose" in th for th in ths):
            tbody = t.find("tbody")
            if not tbody:
                continue
            first_row = tbody.find("tr")
            if not first_row:
                continue
            tds = first_row.find_all("td")
            if tds:
                return _clean(tds[0].get_text(" ", strip=True))
    return None

def _position_from_activity_table(soup: BeautifulSoup) -> Optional[str]:
    """
    Cari tabel dengan header Activity | Organization | Grade | Position.
    Ambil sel 'Position' pada baris pertama.
    """
    for t in soup.find_all("table"):
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

# ---------- H & I dari TIMELINE (yang dikotakin) ----------
def _timeline_fixed_role_and_name(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    """
    Ambil H & I dari kartu di timeline (owl-carousel) yang dikotakin:
    - Targetkan kartu yang H5-nya mengandung 'VICE PRESIDENT' (sesuai contoh).
    - Role = teks <h5>, Name = <p> di bawahnya.
    Jika tidak ketemu, fallback None, None.
    """
    timeline = soup.find(id="timeline-carousel")
    if not timeline:
        return (None, None)

    # Setiap item memiliki struktur: div.item.event-list > div > (div.event-date ... h5) + (div.mt-3 ... p.name)
    for item in timeline.select("div.item.event-list"):
        h5 = item.find("h5")
        if not h5:
            continue
        role_text = h5.get_text(" ", strip=True)
        # Kunci sesuai kotak yang Mas maksud: 'VICE PRESIDENT ...'
        if re.search(r"\bVICE\s+PRESIDENT\b", role_text, flags=re.I):
            # nama ada di <div class="mt-3 px-3"><p class="text-muted">Nama</p>
            p_name = item.find("p", class_=re.compile(r"\btext-muted\b"))
            name_text = p_name.get_text(" ", strip=True) if p_name else None
            return (_clean(role_text), _clean(name_text))

    # Kalau pola 'VICE PRESIDENT' tidak ketemu, sebagai cadangan:
    # cari item dengan ikon check (approved) lalu ambil yang mengandung nama (p.text-muted)
    approved_icons = timeline.select("i.bx.bx.bx-check-circle")
    if approved_icons:
        # ambil parent .item.event-list terdekat dari ikon approved pertama
        icon = approved_icons[0]
        item = icon.find_parent("div", class_=re.compile(r"\bitem\b"))
        if item:
            h5 = item.find("h5")
            p_name = item.find("p", class_=re.compile(r"\btext-muted\b"))
            return (
                _clean(h5.get_text(" ", strip=True)) if h5 else None,
                _clean(p_name.get_text(" ", strip=True)) if p_name else None,
            )

    return (None, None)

# ---------- (Opsional) Fallback lama: last approved dari modal history ----------
def _last_approved_role_and_name_from_history(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
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
    role_text = _clean(role.get_text(" ", strip=True)) if role else None
    name_text = _clean(name.get_text(" ", strip=True)) if name else None
    return (role_text, name_text)

# ---------- Daily Allowance ----------
def _daily_allowance_row(soup: BeautifulSoup) -> Tuple[Optional[str], Optional[str]]:
    """
    Temukan baris 'Daily Allowance' pada tabel transaksi:
    - Ambil '(3 Day)' -> '3'
    - Ambil kolom 'Total' (IDR …)
    """
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue
        first = tds[0].get_text(" ", strip=True).lower()
        if "daily allowance" in first:
            days_text = tds[2].get_text(" ", strip=True) if len(tds) >= 3 else ""
            m = re.search(r"\((\d+)\s*Day", days_text, re.I)
            days = m.group(1) if m else None
            total = tds[-1].get_text(" ", strip=True)
            return (_clean(days), _clean(total))
    return (None, None)

# ---------- Entry point ----------
def parse_html_to_A_to_K(html: str) -> Dict[str, Optional[str]]:
    soup = BeautifulSoup(html, "lxml")

    A = _employee_name_from_top_right(soup)
    B = _h5_suffix_value(soup, "Trip From")
    C = _h5_suffix_value(soup, "Trip To")
    D = _text_after_label(soup, "Depart Date")
    E = _text_after_label(soup, "Return Date")
    F = _purpose_from_first_table(soup)
    G = _position_from_activity_table(soup)

    # H & I: PRIORITAS dari timeline fixed (yang dikotakin).
    H, I = _timeline_fixed_role_and_name(soup)
    if not H and not I:
        # fallback (opsional) ke modal history bila timeline tidak tersedia
        H, I = _last_approved_role_and_name_from_history(soup)

    J, K = _daily_allowance_row(soup)

    return {
        "A": A, "B": B, "C": C, "D": D, "E": E,
        "F": F, "G": G, "H": H, "I": I, "J": J, "K": K
    }
