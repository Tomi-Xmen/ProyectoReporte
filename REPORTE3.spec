# -*- mode: python ; coding: utf-8 -*-
# Compilar con:  pyinstaller REPORTE3.spec
# Sale en dist/REPORTE3/ (REPORTE3.exe + _internal/), la carpeta completa que
# fog_postscript.sh copia a los equipos clonados.


a = Analysis(
    ['REPORTE3.py'],
    pathex=[],
    binaries=[],
    # El ícono también lo usa la ventana en tiempo de ejecución.
    datas=[('favicon.ico', '.')],
    # Se importan dentro de try/except: se nombran para que nunca queden
    # afuera del .exe sin aviso (el envío por SCP dejaría de funcionar).
    hiddenimports=['paramiko', 'scp', 'requests'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Tkinter ya no se usa, y los módulos pesados de Qt que la app no toca no
    # tienen por qué viajar en cada equipo clonado.
    excludes=[
        'tkinter',
        'PySide6.QtQml',
        'PySide6.QtQuick',
        'PySide6.QtPdf',
        'PySide6.QtWebEngineCore',
        'PySide6.QtMultimedia',
        'PySide6.Qt3DCore',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='REPORTE3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['favicon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='REPORTE3',
)
