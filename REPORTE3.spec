# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['REPORTE3.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # paramiko carga los backends de cifrado por nombre en tiempo de ejecución,
    # así que PyInstaller no los ve al analizar los imports y el .exe se queda
    # sin poder autenticar por SSH.
    hiddenimports=[
        'paramiko',
        'scp',
        'cryptography',
        'cryptography.hazmat.backends.openssl',
        'cryptography.hazmat.bindings._rust',
        'nacl',
        'bcrypt',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    # console=True para que --clonacion escriba su traza en el log del
    # post-script de FOG. En el menú normal la consola se esconde sola
    # (_ocultar_consola), así que el operador no la ve.
    console=True,
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
