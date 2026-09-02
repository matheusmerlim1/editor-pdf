@echo off
REM ---------------------------------------------------------------
REM  Gera o executavel EditorPDF.exe (Windows) usando PyInstaller.
REM  Resultado: dist\EditorPDF.exe  (arquivo unico, sem instalacao)
REM ---------------------------------------------------------------

echo.
echo [1/2] Instalando dependencias...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :erro

echo.
echo [2/2] Compilando o executavel...
pyinstaller --noconfirm --onefile --windowed ^
    --name EditorPDF ^
    --icon assets\icone.ico ^
    editor_pdf.py || goto :erro

echo.
echo ====================================================
echo  Pronto! O executavel esta em:  dist\EditorPDF.exe
echo ====================================================
pause
exit /b 0

:erro
echo.
echo *** Ocorreu um erro durante a geracao do executavel. ***
pause
exit /b 1
