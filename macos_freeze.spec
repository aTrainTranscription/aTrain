# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata
import os
import re

# CI sets ATRAIN_VERSION (e.g. 1.5.0 or 0.0.0-test); fail loudly if it is missing
version = os.environ["ATRAIN_VERSION"]

datas = []
datas += collect_data_files('aTrain')
datas += collect_data_files('torch')
datas += collect_data_files('nicegui')
datas += collect_data_files('lightning')
datas += collect_data_files('lightning_fabric')
datas += collect_data_files('lightning_utilities')
datas += collect_data_files('pyannote')
datas += collect_data_files('pyannote.audio.models')
datas += collect_data_files('pyannote.audio.models.segmentation')
datas += collect_data_files('pyannote.audio.models.embedding')
datas += collect_data_files('pytorch_lightning')
datas += collect_data_files('faster_whisper')
datas += collect_data_files('aTrain_core')
datas += copy_metadata('lightning')
datas += copy_metadata('lightning_utilities')
datas += copy_metadata('torch')
datas += copy_metadata('tqdm')
datas += copy_metadata('requests')
datas += copy_metadata('packaging')
datas += copy_metadata('filelock')
datas += copy_metadata('numpy')
datas += copy_metadata('tokenizers')
datas += copy_metadata('pyannote.audio')
datas += copy_metadata('huggingface-hub')
datas += copy_metadata('pyyaml')
datas += copy_metadata('pytorch_lightning')
# aTrain_core is not a separate distribution under the single-pyproject layout
# (it ships inside the aTrain wheel), so copy_metadata('aTrain_core') would raise
# PackageNotFoundError. Its data files are still bundled via collect_data_files
# above; nothing reads aTrain_core's dist metadata at runtime.

hiddenimports = ['pytorch_lightning','pyyaml','huggingface-hub','pyannote','pytorch','lightning']
hiddenimports += collect_submodules('wakepy')
hiddenimports += collect_submodules('pyannote')
hiddenimports += collect_submodules('sklearn')

a = Analysis(
    ['freeze.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    optimize=0,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='aTrain',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['aTrain/static/favicon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='aTrain',
)
app = BUNDLE(
    coll,
    name='aTrain.app',
    icon='aTrain/static/favicon.icns',
    bundle_identifier='at.atrain.bandas',
    version=version,
    info_plist={
        'CFBundleShortVersionString': version,
        'CFBundleVersion': re.split('[-+]', version)[0],
        'LSApplicationCategoryType': 'public.app-category.productivity',
        'NSDocumentsFolderUsageDescription': 'aTrain requires access to your Documents folder to save and manage files.',
        'NSFileAccessUsageDescription': 'aTrain needs access to specific folders for its functionality. Please grant this access in System Preferences > Security & Privacy > Privacy > Files and Folders.',
        'ITSAppUsesNonExemptEncryption': False,
        'LSMinimumSystemVersion': '14.0',
        # App Nap throttles the app while its window is in the background (#307:
        # 12 minutes instead of 22 s for a 12 s file, transcribing in a browser).
        'LSAppNapIsDisabled': True,
    },
)
