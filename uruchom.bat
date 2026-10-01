@echo off
cd /d "%~dp0"
py -3 --version >nul 2>nul && (start "" pyw -3 narzedzia_pdf.py) || (start "" pythonw narzedzia_pdf.py)
