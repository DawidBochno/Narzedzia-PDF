#!/usr/bin/env python3
"""Narzedzia PDF. Laczenie (takze JPG/PNG), dzielenie, wybor i usuwanie
stron, obracanie, kompresja, numeracja stron, znak wodny. Wszystko lokalnie
(PyMuPDF), bez wysylania plikow do serwisow internetowych.

Uruchomienie: python narzedzia_pdf.py            (GUI)
              python narzedzia_pdf.py --selftest (test logiki)
"""
import base64
import hashlib
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(APP_DIR, "ustawienia.json")  # ostatnia operacja, folder wyjsciowy, rozmiar okna

IMAGES = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff")
# czcionka z polskimi znakami do numeracji i znaku wodnego (wbudowana Helvetica ich nie ma)
FONT = next((f for f in (r"C:\Windows\Fonts\arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
             if os.path.exists(f)), None)

# ----------------------------------------------------------------- strony ----


def parse_groups(spec, n):
    """'1-3, 5, 8-' -> [[0,1,2],[4],[7..n-1]] (indeksy od 0). Pusty = kazda strona osobno."""
    spec = spec.replace(" ", "")
    if not spec:
        return [[i] for i in range(n)]
    groups = []
    for part in spec.split(","):
        m = re.fullmatch(r"(\d*)(-?)(\d*)", part)
        if not part or not m or not (m.group(1) or m.group(3)):
            raise ValueError("Niepoprawny zakres stron: %r (przyklad: 1-3,5,8-)" % part)
        a = int(m.group(1) or 1)
        b = int(m.group(3) or n) if m.group(2) else a
        if not 1 <= a <= b <= n:
            raise ValueError("Zakres %r poza dokumentem (stron: %d)" % (part, n))
        groups.append(list(range(a - 1, b)))
    return groups


def parse_pages(spec, n):
    """Jak parse_groups, ale plaska lista bez powtorzen; pusty = wszystkie."""
    if not spec.strip():
        return list(range(n))
    return list(dict.fromkeys(i for g in parse_groups(spec, n) for i in g))


# -------------------------------------------------------------- operacje ----


def _open(path):
    import pymupdf
    if path.lower().endswith(IMAGES):
        img = pymupdf.open(path)
        doc = pymupdf.open("pdf", img.convert_to_pdf())
        img.close()
        return doc
    doc = pymupdf.open(path)
    if doc.needs_pass:
        doc.close()
        raise ValueError("plik zabezpieczony haslem")
    return doc


def _save(doc, dst):
    doc.save(dst, garbage=4, deflate=True)
    doc.close()
    return dst


def _int(value, default, lo, hi, what):
    try:
        v = int(value or default)
    except ValueError:
        v = None
    if v is None or not lo <= v <= hi:
        raise ValueError("%s: podaj liczbe od %d do %d" % (what, lo, hi))
    return v


def _out(out_dir, src, suffix):
    return os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + suffix + ".pdf")


def op_merge(files, out_dir, pages, value, log, unsign=False):
    import pymupdf
    out = pymupdf.open()
    for f in files:
        src = _open(f)
        out.insert_pdf(src)
        log("  + %s (%d str.)" % (os.path.basename(f), len(src)))
        src.close()
    if unsign:
        log("  usunieto pol podpisu: %d - wynik NIE jest podpisany" % _strip_sigs(out))
    name = re.sub(r'[\\/:*?"<>|]', "_", re.sub(r"(?i)\.pdf$", "", value)).strip(" .")
    name = name or "polaczony_%s" % time.strftime("%Y%m%d_%H%M%S")
    dst, k = os.path.join(out_dir, name + ".pdf"), 2
    while os.path.exists(dst):  # nazwa od uzytkownika - nie nadpisywac (np. oryginalu w tym samym folderze)
        dst, k = os.path.join(out_dir, "%s_%d.pdf" % (name, k)), k + 1
    return [_save(out, dst)]


def op_merge_unsign(files, out_dir, pages, value, log):
    return op_merge(files, out_dir, pages, value, log, unsign=True)


def op_split(f, out_dir, pages, value, log):
    import pymupdf
    src, res = _open(f), []
    for g in parse_groups(pages, len(src)):
        out = pymupdf.open()
        for i in g:
            out.insert_pdf(src, from_page=i, to_page=i)
        label = str(g[0] + 1) if len(g) == 1 else "%d-%d" % (g[0] + 1, g[-1] + 1)
        res.append(_save(out, _out(out_dir, f, "_str" + label)))
    src.close()
    return res


def op_select(f, out_dir, pages, value, log):
    src = _open(f)
    src.select(parse_pages(pages, len(src)))
    return [_save(src, _out(out_dir, f, "_wybrane"))]


def op_delete(f, out_dir, pages, value, log):
    if not pages.strip():
        raise ValueError("podaj strony do usuniecia")
    src = _open(f)
    drop = set(parse_pages(pages, len(src)))
    keep = [i for i in range(len(src)) if i not in drop]
    if not keep:
        raise ValueError("nie mozna usunac wszystkich stron")
    src.select(keep)
    return [_save(src, _out(out_dir, f, "_bez_stron"))]


def op_rotate(f, out_dir, pages, value, log):
    angle = _int(value, 90, -270, 270, "kat")
    if angle % 90:
        raise ValueError("kat musi byc wielokrotnoscia 90")
    src = _open(f)
    for i in parse_pages(pages, len(src)):
        src[i].set_rotation((src[i].rotation + angle) % 360)
    return [_save(src, _out(out_dir, f, "_obrocony"))]


def op_compress(f, out_dir, pages, value, log):
    quality = _int(value, 60, 1, 100, "jakosc")
    src = _open(f)
    src.rewrite_images(dpi_threshold=200, dpi_target=150, quality=quality)
    dst = _out(out_dir, f, "_skompresowany")
    src.save(dst, garbage=4, deflate=True, use_objstms=1)
    src.close()
    a, b = os.path.getsize(f), os.path.getsize(dst)
    if b >= a:
        shutil.copyfile(f, dst)
        log("  plik jest juz zoptymalizowany - zapisano kopie bez zmian (%.0f KB)" % (a / 1024))
    else:
        log("  %.0f KB -> %.0f KB (-%.0f%%)" % (a / 1024, b / 1024, (a - b) * 100 / a))
    return [dst]


def _text(page, point, text, size, **kw):
    font = dict(fontname="arial", fontfile=FONT) if FONT else {}
    page.insert_text(point, text, fontsize=size, **font, **kw)


def op_number(f, out_dir, pages, value, log):
    import pymupdf
    fmt = value or "Strona {n} z {N}"
    src = _open(f)
    n_all = len(src)
    for i in parse_pages(pages, n_all):
        page = src[i]
        r = page.rect
        text = fmt.replace("{n}", str(i + 1)).replace("{N}", str(n_all))
        width = pymupdf.get_text_length(text, fontsize=9)  # Helvetica - wystarczy do wysrodkowania
        p = pymupdf.Point((r.width - width) / 2, r.height - 20) * page.derotation_matrix
        _text(page, p, text, 9, rotate=page.rotation)
    return [_save(src, _out(out_dir, f, "_numerowany"))]


def op_show_sigs(f, out_dir, pages, value, log):
    sigs = signatures(f)
    if not sigs:
        log("  brak podpisow elektronicznych")
    for k, s in enumerate(sigs, 1):
        who = s.get("kto") or "?"
        log("  [%d] %s%s" % (k, who, " (wystawca: %s)" % s["wystawca"] if s.get("wystawca") else ""))
        log("      pole \"%s\", strona %d%s%s" % (s["pole"], s["strona"], ", data: " + s["kiedy"] if s.get("kiedy") else "",
                                              ", format: " + s["format"] if s["format"] else ""))
        for key, label in (("powod", "powod"), ("miejsce", "miejsce"), ("cert_do", "certyfikat wazny do")):
            if s.get(key):
                log("      %s: %s" % (label, s[key]))
        if "skrot_ok" in s:
            log("      tresc podpisana: " + ("NIEZMIENIONA (skrot zgodny)" if s["skrot_ok"] else
                                            "ZMIENIONA - skrot niezgodny, podpis NIEWAZNY"))
        if s.get("caly_plik") is False:
            log("      po podpisaniu do pliku dopisano zmiany (podpis dotyczy wczesniejszej wersji dokumentu)")
    if sigs:
        log("  Zaufania i waznosci certyfikatu program nie sprawdza - do tego sluzy walidator (np. gov.pl).")
    return []


def _strip_sigs(doc):
    """Usuwa pola podpisu (z wygladem) i dane walidacyjne; zwraca liczbe usunietych pol."""
    import pymupdf
    n = 0
    for page in doc:
        while True:  # usuwanie w trakcie iteracji widgets() psuje iterator - zawsze pierwszy od nowa
            w = next(page.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE]), None)
            if not w:
                break
            page.delete_widget(w)
            n += 1
    cat = doc.pdf_catalog()
    for key in ("DSS", "Perms", "AcroForm/SigFlags"):  # dane walidacji (LTV), certyfikacja DocMDP, flaga podpisu
        doc.xref_set_key(cat, key, "null")
    return n


def op_unsign(f, out_dir, pages, value, log):
    src = _open(f)
    n = _strip_sigs(src)
    if not n:
        src.close()
        raise ValueError("brak podpisow w pliku")
    log("  usunieto pol podpisu: %d" % n)
    return [_save(src, _out(out_dir, f, "_bez_podpisow"))]


def op_watermark(f, out_dir, pages, value, log):
    import pymupdf
    text = value or "KOPIA"
    src = _open(f)
    for i in parse_pages(pages, len(src)):
        page = src[i]
        r = page.rect
        size = min(r.width, r.height) / max(3, len(text) * 0.6)
        width = pymupdf.get_text_length(text, fontsize=size)
        c = pymupdf.Point(r.width / 2, r.height / 2) * page.derotation_matrix
        start = pymupdf.Point(c.x - width / 2, c.y + size / 3)
        _text(page, start, text, size, color=(0.6, 0.6, 0.6), fill_opacity=0.3,
              morph=(c, pymupdf.Matrix(45 + page.rotation)))
    return [_save(src, _out(out_dir, f, "_znak_wodny"))]


# nazwa: (funkcja, czy laczy wiele plikow, podpowiedz "Strony", podpowiedz "Wartosc")
OPS = {
    "Polacz (PDF, JPG, PNG)": (op_merge, True, "-", "nazwa pliku wynikowego (puste = polaczony_data_godzina)"),
    "Polacz i usun podpisy": (op_merge_unsign, True, "-", "nazwa pliku wynikowego (puste = polaczony_data_godzina)"),
    "Podziel": (op_split, False, "np. 1-3,4-6 (puste = kazda strona osobno)", "-"),
    "Wybierz strony": (op_select, False, "np. 1,3,5-7 (w podanej kolejnosci)", "-"),
    "Usun strony": (op_delete, False, "np. 2,5-6", "-"),
    "Obroc": (op_rotate, False, "puste = wszystkie", "kat: 90 / 180 / 270"),
    "Kompresuj": (op_compress, False, "-", "jakosc JPEG 1-100 (domyslnie 60)"),
    "Numeruj strony": (op_number, False, "puste = wszystkie", "format, domyslnie: Strona {n} z {N}"),
    "Znak wodny": (op_watermark, False, "puste = wszystkie", "tekst, domyslnie: KOPIA"),
    "Wyswietl podpisy": (op_show_sigs, False, "-", "-"),
    "Usun podpisy": (op_unsign, False, "-", "-"),
}


def list_inputs(inp, merge):
    """Plik, folder albo lista plikow/folderow -> lista plikow (folder: alfabetycznie)."""
    exts = (".pdf",) + (IMAGES if merge else ())
    files = []
    for p in inp if isinstance(inp, (list, tuple)) else [inp]:
        if os.path.isdir(p):
            files += sorted(os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(exts))
        else:
            files.append(p)
    return files


def page_count(path):
    try:
        doc = _open(path)
    except Exception:
        return "?"
    n = len(doc)
    doc.close()
    return n


def signed(path):
    """Czy PDF ma zlozony podpis elektroniczny (puste pole podpisu sie nie liczy)."""
    if path.lower().endswith(IMAGES):  # obraz nie ma podpisu - bez kosztownej konwersji
        return False
    try:
        doc = _open(path)
    except Exception:
        return False
    import pymupdf
    res = any(w.is_signed for page in doc for w in page.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE]))
    doc.close()
    return res


def _cms(der, signed_data):
    """Podpisujacy, wystawca, data i zgodnosc skrotu z podpisu CMS (bez sprawdzania zaufania)."""
    try:
        from asn1crypto import cms
    except ImportError:
        return {"kto": "? (brak biblioteki asn1crypto - uruchom install.bat)"}
    try:
        sd = cms.ContentInfo.load(der)["content"]
        si = sd["signer_infos"][0]
        sid = si["sid"]
        certs = [c.chosen for c in sd["certificates"] if c.name == "certificate"]
        if sid.name == "issuer_and_serial_number":
            cert = next((c for c in certs if c.serial_number == sid.chosen["serial_number"].native), None)
        else:
            cert = next((c for c in certs if c.key_identifier == sid.chosen.native), None)
        attrs = {a["type"].native: a["values"][0].native for a in si["signed_attrs"]}
        res = {"skrot_ok": attrs.get("message_digest") == hashlib.new(
            si["digest_algorithm"]["algorithm"].native, signed_data).digest()}
        if attrs.get("signing_time"):
            res["kiedy"] = attrs["signing_time"].astimezone().strftime("%Y-%m-%d %H:%M")
        if cert:
            s, i = cert.subject.native, cert.issuer.native
            res["kto"] = s.get("common_name") or cert.subject.human_friendly
            res["wystawca"] = i.get("common_name") or i.get("organization_name") or cert.issuer.human_friendly
            res["cert_do"] = cert["tbs_certificate"]["validity"]["not_after"].native.strftime("%Y-%m-%d")
        return res
    except Exception as e:
        return {"kto": "? (nie udalo sie odczytac podpisu: %s)" % e}


def signatures(path):
    """Zlozone podpisy w PDF: pole, strona, podpisujacy, data, czy obejmuje caly plik, zgodnosc skrotu."""
    import pymupdf
    if path.lower().endswith(IMAGES):
        return []
    with open(path, "rb") as fh:
        data = fh.read()
    doc = _open(path)
    res = []
    for page in doc:
        for w in page.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE]):
            if not w.is_signed:
                continue
            v = "V" if doc.xref_get_key(w.xref, "V")[0] != "null" else "Parent/V"

            def get(key):
                t, val = doc.xref_get_key(w.xref, v + "/" + key)
                return "" if t == "null" else val.lstrip("/")

            s = {"pole": w.field_name, "strona": page.number + 1, "format": get("SubFilter"),
                 "powod": get("Reason"), "miejsce": get("Location"), "kto": get("Name")}
            m = re.match(r"D:(\d{4})(\d\d)(\d\d)(\d\d)(\d\d)", get("M"))
            if m:
                s["kiedy"] = "%s-%s-%s %s:%s" % m.groups()
            # wartosc podpisu ze slownika (xref_get_key zwraca ja jako tekst, nie bajty) - nie z pliku:
            # po przerobieniu pliku ByteRange moze wskazywac cudzy podpis
            t, val = doc.xref_get_key(w.xref, v)
            obj = doc.xref_object(int(val.split()[0]), compressed=True) if t == "xref" else val
            hexv = re.search(r"/Contents\s*<([0-9A-Fa-f\s]*)>", obj)
            try:
                a, b, c, n = (int(x) for x in get("ByteRange").strip("[]").split())
                hexv = re.sub(r"\s", "", hexv.group(1))
            except (ValueError, AttributeError):
                s["kto"] = s["kto"] or "? (uszkodzony slownik podpisu)"
                res.append(s)
                continue
            s["caly_plik"] = c + n == len(data)
            s.update({k: x for k, x in _cms(bytes.fromhex(hexv), data[a:a + b] + data[c:c + n]).items()
                      if x not in (None, "")})
            if data[a + b:c].strip(b"<>").decode("latin-1").lower() != hexv.lower():
                s["skrot_ok"] = False  # podpis nie lezy tam, gdzie wskazuje ByteRange - plik przerobiony
            res.append(s)
    doc.close()
    return res


SIGN_WARN = ("UWAGA: pliki z podpisem elektronicznym: %s\n"
             "  Podpis obejmuje dokladnie ten plik - po kazdej zmianie (laczenie, obracanie, numeracja...)\n"
             "  podpis w wyniku NIE BEDZIE WAZNY. Podpisane dokumenty przekaz w oryginale (osobno)\n"
             "  albo podpisz wynik ponownie.")


def thumbnail(path, size=220):
    """PNG pierwszej strony, dluzszy bok = size px (podglad w oknie)."""
    import pymupdf
    doc = _open(path)
    page = doc[0]
    z = size / max(page.rect.width, page.rect.height)
    png = page.get_pixmap(matrix=pymupdf.Matrix(z, z)).tobytes("png")
    doc.close()
    return png


def load_settings(path=SETTINGS):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(data, path=SETTINGS):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except OSError:  # np. folder tylko do odczytu - ustawienia nie sa niezbedne
        pass


def run(op, inp, out_dir, pages="", value="", log=print):
    func, merge, _, _ = OPS[op]
    files = list_inputs(inp, merge)
    if not files:
        log("Brak plikow do przetworzenia.")
        return []
    os.makedirs(out_dir, exist_ok=True)
    sig = [os.path.basename(f) for f in files if func not in (op_show_sigs, op_unsign, op_merge_unsign) and signed(f)]
    if sig:
        log(SIGN_WARN % ", ".join(sig))
    jobs = [files] if merge else files
    res = []
    for job in jobs:
        name = "%d plikow" % len(job) if merge else os.path.basename(job)
        log("%s: %s" % (op, name))
        try:
            for dst in func(job, out_dir, pages, value.strip(), log):
                log("  OK -> %s" % dst)
                res.append(dst)
        except Exception as e:
            log("  BLAD: %s" % e if isinstance(e, ValueError) else "  BLAD:\n" + traceback.format_exc())
    log("Zakonczono.")
    return res


# -------------------------------------------------------------------- GUI ----


def gui():
    import tkinter as tk
    from tkinter import filedialog, ttk, scrolledtext

    try:  # przeciaganie plikow z Eksploratora; bez biblioteki program dziala, tylko bez tego
        from tkinterdnd2 import TkinterDnD, DND_FILES
        root = TkinterDnD.Tk()
    except ImportError:
        root, DND_FILES = tk.Tk(), None
    root.title("Narzedzia PDF")
    cfg = load_settings()
    root.geometry(cfg.get("size", "1040x720"))  # sam rozmiar - pozycja mogla byc na odlaczonym monitorze
    pad = dict(padx=6, pady=3)

    v_op = tk.StringVar(value=cfg.get("op") if cfg.get("op") in OPS else next(iter(OPS)))
    out_default = os.path.join(APP_DIR, "OUTPUT")
    v_out = tk.StringVar(value=cfg.get("out") or out_default)
    v_pages, v_value = tk.StringVar(), tk.StringVar()
    items, counts, sigs = [], {}, set()  # pliki na liscie (kolejnosc = kolejnosc laczenia), liczba stron

    top = ttk.Frame(root)
    top.pack(fill="x", **pad)
    ttk.Label(top, text="Operacja:").pack(side="left", **pad)
    ttk.Combobox(top, textvariable=v_op, values=list(OPS), state="readonly",
                 width=30).pack(side="left", **pad)

    lf = ttk.LabelFrame(root, text="Pliki - " + ("przeciagnij tutaj pliki lub foldery. " if DND_FILES else "")
                        + "Kolejnosc na liscie = kolejnosc laczenia (przeciagnij wiersz mysza albo W gore / W dol)")
    lf.pack(fill="both", expand=True, **pad)
    lb = tk.Listbox(lf, selectmode="extended", height=10, activestyle="none")
    sb = ttk.Scrollbar(lf, command=lb.yview)
    lb.config(yscrollcommand=sb.set)
    lb.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
    sb.pack(side="left", fill="y", pady=6)
    side = ttk.Frame(lf)
    side.pack(side="left", fill="y", padx=6, pady=6)
    box = ttk.Frame(lf, width=230, height=230, relief="groove")
    box.pack(side="left", anchor="n", padx=6, pady=6)
    box.pack_propagate(False)  # staly rozmiar - okno nie skacze przy zmianie podgladu
    preview = ttk.Label(box, anchor="center", justify="center", foreground="#666")
    preview.pack(fill="both", expand=True)
    thumbs = {}
    status = ttk.Label(root, foreground="#666")

    def show_preview(*_):
        sel = lb.curselection()
        if not sel:
            return preview.config(image="", text="Podglad pierwszej strony:\nzaznacz plik na liscie")
        p = items[sel[0]]
        if p not in thumbs:
            try:
                thumbs[p] = tk.PhotoImage(data=base64.b64encode(thumbnail(p)))
            except Exception:
                thumbs[p] = None
        preview.config(image=thumbs[p] or "", text="" if thumbs[p] else "Brak podgladu")

    def refresh(select=()):
        lb.delete(0, "end")
        for i, p in enumerate(items, 1):
            lb.insert("end", "%2d.  %s   (%s str.%s)" % (i, os.path.basename(p), counts[p],
                                                        ", PODPISANY" if p in sigs else ""))
        for i in select:
            lb.selection_set(i)
        if select:
            lb.see(select[0])
        total = sum(c for c in counts.values() if c != "?")
        n_sig = sum(p in sigs for p in items)
        status.config(text="Plikow: %d, stron razem: %d" % (len(items), total) if items else
                      "Lista jest pusta - dodaj pliki przyciskiem lub przeciagnij je na liste.",
                      foreground="#666")
        if n_sig:
            status.config(text=status.cget("text") + "   |   Podpisane: %d - po zmianie podpis nie bedzie wazny"
                          % n_sig, foreground="#b35c00")
        show_preview()

    def add(paths):
        skipped = []
        for p in map(os.path.normpath, list_inputs(list(paths), True)):
            if not p.lower().endswith((".pdf",) + IMAGES):
                skipped.append(os.path.basename(p))
            elif p not in counts:
                items.append(p)
                counts[p] = 1 if p.lower().endswith(IMAGES) else page_count(p)
                if signed(p):
                    sigs.add(p)
        if skipped:
            log("Pominieto (to nie PDF ani obraz): " + ", ".join(skipped))
        refresh()

    def move(d):
        sel = list(lb.curselection())
        if not sel or sel[0] + d < 0 or sel[-1] + d >= len(items):
            return
        for i in sel if d < 0 else reversed(sel):
            items[i + d], items[i] = items[i], items[i + d]
        refresh([i + d for i in sel])

    def remove(*_):
        for i in reversed(lb.curselection()):
            counts.pop(items.pop(i))
        refresh()

    def clear():
        items.clear()
        counts.clear()
        refresh()

    def sort_az():
        items.sort(key=lambda p: os.path.basename(p).lower())
        refresh()

    drag = {}

    def on_press(e):
        i = lb.nearest(e.y)
        box = lb.bbox(i) if items else None
        drag["i"] = i if box and e.y < box[1] + box[3] else None  # klik w pusta czesc listy - nic

    def on_motion(e):  # przeciaganie wiersza zmienia kolejnosc
        i, j = drag.get("i"), lb.nearest(e.y)
        if i is not None and items and j != i:
            items.insert(j, items.pop(i))
            refresh([j])
            drag["i"] = j
        return "break"

    def open_item(e):
        i = lb.nearest(e.y)
        if items and hasattr(os, "startfile"):
            os.startfile(items[i])

    lb.bind("<Button-1>", on_press)
    lb.bind("<B1-Motion>", on_motion)
    lb.bind("<Double-Button-1>", open_item)
    lb.bind("<Delete>", remove)
    lb.bind("<<ListboxSelect>>", show_preview)
    if DND_FILES:
        for w in (lb, lf):
            w.drop_target_register(DND_FILES)
            w.dnd_bind("<<Drop>>", lambda e: add(root.tk.splitlist(e.data)))

    types = [("PDF i obrazy", "*.pdf *.jpg *.jpeg *.png *.bmp *.tif *.tiff")]
    in_dir = os.path.join(APP_DIR, "INPUT")
    for text, cmd in (("Dodaj pliki...", lambda: add(filedialog.askopenfilenames(filetypes=types, initialdir=in_dir))),
                      ("Dodaj folder...", lambda: add([d] if (d := filedialog.askdirectory(initialdir=in_dir)) else [])),
                      (None, None),
                      ("W gore", lambda: move(-1)), ("W dol", lambda: move(1)), ("Sortuj A-Z", sort_az),
                      (None, None),
                      ("Usun z listy", remove), ("Wyczysc liste", clear)):
        if text:
            ttk.Button(side, text=text, command=cmd, width=16).pack(pady=2)
        else:
            ttk.Separator(side).pack(fill="x", pady=6)
    status.pack(anchor="w", padx=12)

    f = ttk.Frame(root)
    f.pack(fill="x", **pad)
    ttk.Label(f, text="Folder wyjsciowy:").grid(row=2, column=0, sticky="w", **pad)
    ttk.Entry(f, textvariable=v_out, width=62).grid(row=2, column=1, **pad)
    ttk.Button(f, text="Wybierz...", command=lambda: v_out.set(
        filedialog.askdirectory() or v_out.get())).grid(row=2, column=2, **pad)

    ttk.Label(f, text="Strony:").grid(row=3, column=0, sticky="w", **pad)
    e_pages = ttk.Entry(f, textvariable=v_pages, width=62)
    e_pages.grid(row=3, column=1, **pad)
    h_pages = ttk.Label(f, foreground="#666")
    h_pages.grid(row=4, column=1, sticky="w", padx=6)
    ttk.Label(f, text="Wartosc:").grid(row=5, column=0, sticky="w", **pad)
    e_value = ttk.Entry(f, textvariable=v_value, width=62)
    e_value.grid(row=5, column=1, **pad)
    h_value = ttk.Label(f, foreground="#666")
    h_value.grid(row=6, column=1, sticky="w", padx=6)

    def on_op(*_):
        _, _, hp, hv = OPS[v_op.get()]
        h_pages.config(text=hp)
        h_value.config(text=hv)
        e_pages.config(state="disabled" if hp == "-" else "normal")
        e_value.config(state="disabled" if hv == "-" else "normal")
        v_value.set("")  # np. kat 90 z Obroc nie moze zostac nazwa pliku przy Polacz

    v_op.trace_add("write", on_op)
    on_op()

    bar = ttk.Frame(root)
    bar.pack(pady=6)
    btn = ttk.Button(bar, text="Wykonaj")
    btn.pack(side="left", padx=6)

    def open_out():
        out = v_out.get().strip('" ')
        if out and hasattr(os, "startfile"):
            os.makedirs(out, exist_ok=True)
            os.startfile(out)

    ttk.Button(bar, text="Otworz folder wynikow", command=open_out).pack(side="left", padx=6)

    log_box = scrolledtext.ScrolledText(root, height=8)
    log_box.pack(fill="both", expand=True, **pad)

    def log(msg):
        def put():
            log_box.insert("end", str(msg) + "\n")
            log_box.see("end")
        root.after(0, put)

    def start():
        inp = list(items)
        out = v_out.get().strip('" ')
        if not inp:
            return log("Dodaj pliki do listy (przycisk 'Dodaj pliki...' albo przeciagnij je na liste).")
        if not out:
            return log("Wskaz folder wyjsciowy.")
        op = v_op.get()
        _, _, hp, hv = OPS[op]
        pages = "" if hp == "-" else v_pages.get()
        value = "" if hv == "-" else v_value.get()
        btn.config(state="disabled")
        log_box.delete("1.0", "end")

        def work():
            try:
                run(op, inp, out, pages, value, log)
            finally:
                root.after(0, lambda: btn.config(state="normal"))

        threading.Thread(target=work, daemon=True).start()

    btn.config(command=start)

    def on_close():
        out = v_out.get().strip('" ')
        save_settings({"op": v_op.get(),
                       # domyslny OUTPUT nie zapisany - po przeniesieniu programu ma wskazywac nowe miejsce
                       "out": "" if os.path.normpath(out) == os.path.normpath(out_default) else out,
                       # zminimalizowane/zmaksymalizowane okno - zostaje poprzedni rozmiar
                       "size": "%dx%d" % (root.winfo_width(), root.winfo_height())
                       if root.state() == "normal" else cfg.get("size", "1040x720")})
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    add([in_dir] if os.path.isdir(in_dir) else [])  # dotychczasowy sposob: pliki wrzucone do INPUT
    if "--selftest" in sys.argv:
        root.after(200, root.destroy)
    import aktualizacja
    aktualizacja.start(root, "DawidBochno/Narzedzia-PDF", "main", "narzedzia_pdf.py")
    root.mainloop()


# --------------------------------------------------------------- selftest ----


def selftest():
    import tempfile
    import pymupdf

    assert parse_groups("", 3) == [[0], [1], [2]]
    assert parse_groups("1-2, 3", 5) == [[0, 1], [2]]
    assert parse_groups("4-", 5) == [[3, 4]] and parse_groups("-2", 5) == [[0, 1]]
    assert parse_pages("3,1,3", 5) == [2, 0]
    for bad in ("0", "6", "3-2", "a", "1,,2"):
        try:
            parse_groups(bad, 5)
            raise AssertionError("powinien byc blad: " + bad)
        except ValueError:
            pass

    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "out")
    src = os.path.join(tmp, "a.pdf")
    d = pymupdf.open()
    for i in range(5):
        d.new_page().insert_text((72, 72), "Tresc strony %d" % (i + 1))
    d.save(src)
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300), False)
    pix.set_rect(pix.irect, (200, 30, 30))
    img = os.path.join(tmp, "b.png")
    pix.save(img)
    quiet = lambda m: None  # noqa: E731

    def pages_of(p):
        with pymupdf.open(p) as x:
            return [pg.get_text().replace("\xa0", " ") for pg in x]

    r = run("Polacz (PDF, JPG, PNG)", [src, img], out, log=quiet)
    assert len(pages_of(r[0])) == 6
    # kolejnosc z listy, nazwa z pola Wartosc (bez niedozwolonych znakow), folder na liscie rozwiniety
    r = run("Polacz (PDF, JPG, PNG)", [img, src], out, value="umowa: skan.pdf", log=quiet)
    assert os.path.basename(r[0]) == "umowa_ skan.pdf" and pages_of(r[0])[1].strip() == "Tresc strony 1"
    r2 = run("Polacz (PDF, JPG, PNG)", [src], out, value="umowa: skan", log=quiet)
    assert os.path.basename(r2[0]) == "umowa_ skan_2.pdf", r2
    assert list_inputs([img, tmp], True) == [img, src, img] and list_inputs(tmp, False) == [src]
    assert page_count(src) == 5 and page_count(os.path.join(tmp, "brak.pdf")) == "?"
    r = run("Podziel", src, out, "1-2,3-5", log=quiet)
    assert [len(pages_of(x)) for x in r] == [2, 3] and r[1].endswith("_str3-5.pdf")
    r = run("Wybierz strony", src, out, "5,1", log=quiet)
    assert [t.strip() for t in pages_of(r[0])] == ["Tresc strony 5", "Tresc strony 1"]
    r = run("Usun strony", src, out, "2-4", log=quiet)
    assert len(pages_of(r[0])) == 2
    assert run("Usun strony", src, out, "1-5", log=quiet) == []
    msgs = []
    assert run("Kompresuj", src, out, "", "abc", log=msgs.append) == []
    assert "jakosc: podaj liczbe od 1 do 100" in "".join(msgs), msgs
    assert run("Obroc", src, out, "", "45", log=quiet) == []
    r = run("Obroc", src, out, "2", "90", log=quiet)
    with pymupdf.open(r[0]) as x:
        assert [p.rotation for p in x] == [0, 90, 0, 0, 0]
    r = run("Numeruj strony", src, out, log=quiet)
    assert "Strona 3 z 5" in pages_of(r[0])[2]
    r = run("Znak wodny", src, out, "", "NIEWAŻNE", log=quiet)
    assert "NIEWAŻNE" in pages_of(r[0])[0]
    r = run("Kompresuj", os.path.join(out, os.listdir(out)[0]), out, log=quiet)
    assert len(r) == 1
    # drugi raz ten sam plik: wynik nie bylby mniejszy -> kopia bez zmian
    msgs = []
    r2 = run("Kompresuj", r[0], os.path.join(out, "2"), log=msgs.append)
    assert len(r2) == 1 and "zapisano kopie bez zmian" in "".join(msgs), msgs
    # podpis: zlozony -> ostrzezenie przy kazdej operacji; puste pole podpisu -> bez ostrzezenia
    for name, value in (("podpisany.pdf", "<</Type/Sig/Filter/Adobe.PPKLite/ByteRange[0 0 0 0]/Contents<00>>>"),
                        ("pole.pdf", None)):
        d = pymupdf.open()
        w = pymupdf.Widget()
        w.field_type, w.field_name, w.rect = pymupdf.PDF_WIDGET_TYPE_SIGNATURE, "Podpis", pymupdf.Rect(50, 50, 200, 90)
        d.new_page().add_widget(w)
        if value:
            d.xref_set_key(next(d[0].widgets()).xref, "V", value)
        d.save(os.path.join(tmp, name))
    assert signed(os.path.join(tmp, "podpisany.pdf")) and not signed(os.path.join(tmp, "pole.pdf"))
    assert not signed(src) and not signed(img)
    msgs = []
    run("Polacz (PDF, JPG, PNG)", [src, os.path.join(tmp, "podpisany.pdf")], out, log=msgs.append)
    assert "podpisem elektronicznym: podpisany.pdf" in msgs[0], msgs
    msgs = []
    run("Obroc", os.path.join(tmp, "pole.pdf"), out, log=msgs.append)
    assert not any("UWAGA" in m for m in msgs), msgs
    assert signatures(os.path.join(tmp, "podpisany.pdf"))[0]["kto"].startswith("?")  # smieci zamiast CMS
    # prawdziwy podpis PAdES (fikcyjny certyfikat): odczyt, uniewaznienie przez laczenie, usuniecie
    ex = os.path.join(APP_DIR, "przyklad", "podpisany_przyklad.pdf")
    s = signatures(ex)
    assert len(s) == 1 and s[0]["kto"] == "Jan Testowy (fikcyjny)" and s[0]["skrot_ok"] and s[0]["caly_plik"], s
    assert s[0]["wystawca"] == "Testowe CA (fikcyjne)" and s[0]["powod"] == "Akceptacja dokumentu", s
    r = run("Polacz (PDF, JPG, PNG)", [src, ex], out, log=quiet)
    s = signatures(r[0])
    assert len(s) == 1 and s[0]["strona"] == 6 and s[0]["skrot_ok"] is False, s
    msgs = []
    assert run("Wyswietl podpisy", [ex, src], out, log=msgs.append) == []
    text = "\n".join(msgs)
    assert "NIEZMIENIONA" in text and "brak podpisow" in text and "UWAGA" not in text, text
    msgs = []
    r2 = run("Polacz i usun podpisy", [src, ex], out, value="bez", log=msgs.append)
    assert signatures(r2[0]) == [] and len(pages_of(r2[0])) == 6, r2
    text = "\n".join(msgs)
    assert "usunieto pol podpisu: 1 - wynik NIE jest podpisany" in text and "UWAGA" not in text, text
    r = run("Usun podpisy", [r[0], src], out, log=quiet)
    assert len(r) == 1 and signatures(r[0]) == [] and not signed(r[0]) and len(pages_of(r[0])) == 6
    png = thumbnail(src)
    pix = pymupdf.Pixmap(png)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and max(pix.width, pix.height) == 220
    assert thumbnail(img)[:4] == b"\x89PNG"
    cfg = os.path.join(tmp, "ustawienia.json")
    assert load_settings(cfg) == {}
    save_settings({"op": "Obroc", "out": "C:\\Wyniki ąę"}, cfg)
    assert load_settings(cfg) == {"op": "Obroc", "out": "C:\\Wyniki ąę"}
    open(cfg, "w").write("{zepsuty")
    assert load_settings(cfg) == {}
    import aktualizacja
    aktualizacja.selftest()
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        if "--gui" in sys.argv:
            gui()
    else:
        gui()
