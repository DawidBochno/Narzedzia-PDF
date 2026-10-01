# Narzędzia PDF

Program **lokalny** — działa w całości na Twoim komputerze i nigdzie nie
wysyła plików. Zastępuje internetowe serwisy typu „połącz PDF online”, do
których trafiają dokumenty z danymi osobowymi.

## Operacje

| Operacja | Pole „Strony” | Pole „Wartość” | Wynik |
|----------|---------------|----------------|-------|
| **Połącz (PDF, JPG, PNG)** | – | – | `polaczony_RRRRMMDD_GGMMSS.pdf` |
| **Podziel** | `1-3,4-6` → dwa pliki; puste → każda strona osobno | – | `nazwa_str1-3.pdf`, … |
| **Wybierz strony** | `1,3,5-7` (w podanej kolejności) | – | `nazwa_wybrane.pdf` |
| **Usuń strony** | `2,5-6` | – | `nazwa_bez_stron.pdf` |
| **Obróć** | puste = wszystkie | `90` / `180` / `270` | `nazwa_obrocony.pdf` |
| **Kompresuj** | – | jakość JPEG 1–100 (domyślnie 60) | `nazwa_skompresowany.pdf` |
| **Numeruj strony** | puste = wszystkie | format, domyślnie `Strona {n} z {N}` | `nazwa_numerowany.pdf` |
| **Znak wodny** | puste = wszystkie | tekst, domyślnie `KOPIA` | `nazwa_znak_wodny.pdf` |

Zakresy stron: `1-3` (od 1 do 3), `5` (jedna strona), `8-` (od 8 do końca),
`-4` (od początku do 4), łączone przecinkiem. Strony liczone są od 1.

Wskazany **folder** jest przetwarzany w całości: każdy plik osobno, a przy
łączeniu wszystkie razem, w kolejności alfabetycznej. Jeśli kolejność
łączenia ma znaczenie, nazwij pliki `01_…`, `02_…`. Przy wyborze kilku
plików przyciskiem **Pliki…** kolejność ustala okno wyboru.

### Szczegóły

- **Łączenie** przyjmuje też zdjęcia i skany (JPG, PNG, BMP, TIFF). Każdy
  obraz staje się jedną stroną, co przydaje się przy skanach z telefonu.
- **Kompresja** zmniejsza obrazy powyżej 200 DPI do 150 DPI i zapisuje je
  jako JPEG z podaną jakością. Najwięcej daje przy skanach. Jeśli plik jest
  już zoptymalizowany i wynik wyszedłby większy, zapisywana jest kopia bez
  zmian.
- **Numeracja i znak wodny** obsługują polskie znaki (czcionka Arial
  z Windows) i poprawnie układają się na stronach obróconych i poziomych.
- **Oryginały nigdy nie są zmieniane.** Wyniki trafiają do folderu
  wyjściowego.

## Szybki start

1. `install.bat` — instaluje bibliotekę `PyMuPDF` i uruchamia self-test.
2. Wrzuć pliki do folderu `INPUT` albo wskaż je przyciskiem **Pliki…**.
3. `uruchom.bat` → wybierz operację → **Wykonaj**.
4. Wyniki są w folderze `OUTPUT`.

Wymaga Pythona 3.9+ z opcjami „Add python.exe to PATH” i „tcl/tk and IDLE”.

## Ograniczenia

- PDF zabezpieczony hasłem trzeba najpierw odbezpieczyć.
- Kompresja nie zmniejszy PDF-ów zawierających sam tekst, bez obrazów,
  bo nie ma w nich czego zmniejszać.
- Znak wodny jest dodawany jako tekst na stronie, a nie jako zabezpieczenie.
  Da się go usunąć w edytorze PDF.

## Testy

```bash
python narzedzia_pdf.py --selftest
```

Test sprawdza parsowanie zakresów stron (także błędnych) i każdą operację
na wygenerowanym PDF-ie, w tym łączenie PDF z obrazem PNG i polskie znaki
w znaku wodnym.
