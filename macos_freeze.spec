# -*- mode: python ; coding: utf-8 -*-
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata
from importlib.resources import files

icon_path = str(files("aTrain.static").joinpath("favicon"))

datas = []
datas += collect_data_files('aTrain')
datas += [(str(files("speechbrain").joinpath("")),'speechbrain')]
datas += collect_data_files('torch')
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
datas += collect_data_files('nagisa')
datas += copy_metadata('nagisa')
datas += copy_metadata('soynlp')
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
datas += copy_metadata('aTrain_core')

hiddenimports = ['pytorch_lightning','pyyaml','huggingface-hub','speechbrain','pyannote','pytorch','lightning']
hiddenimports += collect_submodules('wakepy')
hiddenimports += collect_submodules('speechbrain')
hiddenimports += collect_submodules('pyannote')
hiddenimports += collect_submodules('sklearn')
hiddenimports += collect_submodules('transformers.models.qwen3_asr')

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
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['aTrain/static/favicon.icns'],
    plist='Info.plist'
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='aTrain',
)
app = BUNDLE(
    coll,
    name='aTrain.app',
    icon='aTrain/static/favicon.icns',
    bundle_identifier='at.atrain.bandas',
)
