"""Compile original source with the installed Android SDK; never install or run it."""
import os
from pathlib import Path
import subprocess
import zipfile

from theseus.android import engines


SDK = Path(os.environ.get('ANDROID_HOME', str(Path.home()/'AppData/Local/Android/Sdk')))
BUILD = SDK/'build-tools/35.0.0'
PLATFORM = SDK/'platforms/android-36/android.jar'


def android_fixture(directory):
    original = Path(__file__).parent/'fixtures/android'
    tools = engines()
    classes, dex = directory/'classes', directory/'dex'
    classes.mkdir(parents=True)
    dex.mkdir()
    def execute(command):
        completed = subprocess.run(command,capture_output=True)
        assert completed.returncode == 0, (command,completed.stdout,completed.stderr)
    execute([tools['javac'], '-encoding','UTF-8','--release','8','-classpath',str(PLATFORM),'-d',str(classes),
        *map(str,original.glob('*.java'))])
    commands = [
        [tools['java'],'-cp',str(BUILD/'lib/d8.jar'),'com.android.tools.r8.D8','--min-api','23',
            '--lib',str(PLATFORM),'--output',str(dex),*map(str,classes.rglob('*.class'))],
        [str(BUILD/'aapt2.exe'),'compile','--dir',str(original/'res'),'-o',str(directory/'resources.zip')],
        [str(BUILD/'aapt2.exe'),'link','-o',str(directory/'fixture.apk'),'--manifest',str(original/'AndroidManifest.xml'),
            '-I',str(PLATFORM),str(directory/'resources.zip')],
    ]
    for command in commands:
        execute(command)
    with zipfile.ZipFile(directory/'fixture.apk','a') as apk:
        apk.write(dex/'classes.dex','classes.dex')
    return directory/'fixture.apk'
