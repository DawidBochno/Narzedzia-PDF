#!/usr/bin/env python3
"""Narzedzia PDF. Laczenie (takze JPG/PNG), dzielenie, wybor i usuwanie
stron, obracanie, kompresja, numeracja stron, znak wodny. Wszystko lokalnie
(PyMuPDF), bez wysylania plikow do serwisow internetowych.

Uruchomienie: python narzedzia_pdf.py            (GUI)
              python narzedzia_pdf.py --selftest (test logiki)
"""
import os
import re
import sys
import threading
import time
import traceback

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

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
        raise ValueError("plik zabezpieczony haslem")
    return doc


def _save(doc, dst):
    doc.save(dst, garbage=4, deflate=True)
    doc.close()
    return dst


def _out(out_dir, src, suffix):
    return os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + suffix + ".pdf")


def op_merge(files, out_dir, pages, value, log):
    import pymupdf
    out = pymupdf.open()
    for f in files:
        src = _open(f)
        out.insert_pdf(src)
        log("  + %s (%d str.)" % (os.path.basename(f), len(src)))
        src.close()
    return [_save(out, os.path.join(out_dir, "polaczony_%s.pdf" % time.strftime("%Y%m%d_%H%M%S")))]


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
    angle = int(value or 90)
    if angle % 90:
        raise ValueError("kat musi byc wielokrotnoscia 90")
    src = _open(f)
    for i in parse_pages(pages, len(src)):
        src[i].set_rotation((src[i].rotation + angle) % 360)
    return [_save(src, _out(out_dir, f, "_obrocony"))]


def op_compress(f, out_dir, pages, value, log):
    quality = int(value or 60)
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
    "Polacz (PDF, JPG, PNG)": (op_merge, True, "-", "-"),
    "Podziel": (op_split, False, "np. 1-3,4-6 (puste = kazda strona osobno)", "-"),
    "Wybierz strony": (op_select, False, "np. 1,3,5-7 (w podanej kolejnosci)", "-"),
    "Usun strony": (op_delete, False, "np. 2,5-6", "-"),
    "Obroc": (op_rotate, False, "puste = wszystkie", "kat: 90 / 180 / 270"),
    "Kompresuj": (op_compress, False, "-", "jakosc JPEG 1-100 (domyslnie 60)"),
    "Numeruj strony": (op_number, False, "puste = wszystkie", "format, domyslnie: Strona {n} z {N}"),
    "Znak wodny": (op_watermark, False, "puste = wszystkie", "tekst, domyslnie: KOPIA"),
}


def list_inputs(inp, merge):
    if isinstance(inp, (list, tuple)):
        files = list(inp)
    elif os.path.isdir(inp):
        exts = (".pdf",) + (IMAGES if merge else ())
        files = sorted(os.path.join(inp, f) for f in os.listdir(inp) if f.lower().endswith(exts))
    else:
        files = [inp]
    return files


def run(op, inp, out_dir, pages="", value="", log=print):
    func, merge, _, _ = OPS[op]
    files = list_inputs(inp, merge)
    if not files:
        log("Brak plikow do przetworzenia.")
        return []
    os.makedirs(out_dir, exist_ok=True)
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

    root = tk.Tk()
    root.title("Narzedzia PDF")
    root.geometry("800x560")
    pad = dict(padx=6, pady=3)

    v_op = tk.StringVar(value=next(iter(OPS)))
    v_in = tk.StringVar(value=os.path.join(APP_DIR, "INPUT"))
    v_out = tk.StringVar(value=os.path.join(APP_DIR, "OUTPUT"))
    v_pages, v_value = tk.StringVar(), tk.StringVar()
    picked = []  # pliki wybrane przyciskiem "Pliki..." (zachowana kolejnosc)

    f = ttk.Frame(root)
    f.pack(fill="x", **pad)
    ttk.Label(f, text="Operacja:").grid(row=0, column=0, sticky="w", **pad)
    ttk.Combobox(f, textvariable=v_op, values=list(OPS), state="readonly",
                 width=30).grid(row=0, column=1, sticky="w", **pad)

    def pick_files():
        fs = filedialog.askopenfilenames(filetypes=[("PDF i obrazy", "*.pdf *.jpg *.jpeg *.png *.bmp *.tif *.tiff")])
        if fs:
            picked[:] = fs
            v_in.set(" | ".join(os.path.basename(x) for x in fs))

    def pick_dir():
        d = filedialog.askdirectory()
        if d:
            picked.clear()
            v_in.set(d)

    ttk.Label(f, text="Pliki lub folder:").grid(row=1, column=0, sticky="w", **pad)
    e_in = ttk.Entry(f, textvariable=v_in, width=62)
    e_in.grid(row=1, column=1, **pad)
    e_in.bind("<Key>", lambda e: picked.clear())
    ttk.Button(f, text="Pliki...", command=pick_files).grid(row=1, column=2, **pad)
    ttk.Button(f, text="Folder...", command=pick_dir).grid(row=1, column=3, **pad)
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

    v_op.trace_add("write", on_op)
    on_op()

    log_box = scrolledtext.ScrolledText(root, height=14)
    log_box.pack(fill="both", expand=True, **pad)

    def log(msg):
        def put():
            log_box.insert("end", str(msg) + "\n")
            log_box.see("end")
        root.after(0, put)

    btn = ttk.Button(root, text="Wykonaj")
    btn.pack(pady=6)

    def start():
        inp = list(picked) or v_in.get().strip('" ')
        out = v_out.get().strip('" ')
        if not picked and not os.path.exists(inp):
            return log("Wskaz istniejacy plik lub folder.")
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
    if "--selftest" in sys.argv:
        root.after(200, root.destroy)
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
    r = run("Podziel", src, out, "1-2,3-5", log=quiet)
    assert [len(pages_of(x)) for x in r] == [2, 3] and r[1].endswith("_str3-5.pdf")
    r = run("Wybierz strony", src, out, "5,1", log=quiet)
    assert [t.strip() for t in pages_of(r[0])] == ["Tresc strony 5", "Tresc strony 1"]
    r = run("Usun strony", src, out, "2-4", log=quiet)
    assert len(pages_of(r[0])) == 2
    assert run("Usun strony", src, out, "1-5", log=quiet) == []
    r = run("Obroc", src, out, "2", "90", log=quiet)
    with pymupdf.open(r[0]) as x:
        assert [p.rotation for p in x] == [0, 90, 0, 0, 0]
    r = run("Numeruj strony", src, out, log=quiet)
    assert "Strona 3 z 5" in pages_of(r[0])[2]
    r = run("Znak wodny", src, out, "", "NIEWAŻNE", log=quiet)
    assert "NIEWAŻNE" in pages_of(r[0])[0]
    r = run("Kompresuj", os.path.join(out, os.listdir(out)[0]), out, log=quiet)
    assert len(r) == 1
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
        if "--gui" in sys.argv:
            gui()
    else:
        gui()
