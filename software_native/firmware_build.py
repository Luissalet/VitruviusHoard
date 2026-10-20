"""Build self-contained analysis resources for the installed product."""
from pathlib import Path
import os
import json
import shutil
import subprocess

from setuptools.command.build_py import build_py
from setuptools.command.bdist_wheel import bdist_wheel


class BuildPy(build_py):
    def run(self):
        root = Path(__file__).resolve().parent.parent
        cargo = shutil.which('cargo')
        target = None
        if cargo:
            manifest = root / 'software_native/engine/firmware-scanner/Cargo.toml'
            target = root / '.cargo-target' if self.editable_mode else Path(
                self.get_finalized_command('build').build_temp).resolve() / 'firmware-scanner'
            subprocess.run([cargo, 'build', '--release', '--locked', '--jobs', '2',
                            '--manifest-path', str(manifest), '--target-dir', str(target)], cwd=root, check=True)
        else:
            self.announce('Cargo unavailable: firmware signatures use a configured Binwalk client.', level=2)
        super().run()
        if self.editable_mode:
            return
        engine = Path(self.build_lib).resolve() / 'software_native/engine'
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if npm is None:
            raise RuntimeError('npm is required to package the native JavaScript analysis engine')
        # Assemble dependencies inside build_lib, never in an installed app or
        # another checkout. Preserve the per-module layout and package assets.
        subprocess.run([npm, 'ci', '--bin-links=false', '--no-audit', '--no-fund'], cwd=engine, check=True)
        subprocess.run([npm, 'run', 'build'], cwd=engine, check=True)
        subprocess.run([npm, 'prune', '--omit=dev', '--bin-links=false', '--no-audit', '--no-fund'], cwd=engine, check=True)
        if target:
            name = 'theseus-firmware-scanner' + ('.exe' if os.name == 'nt' else '')
            destination = engine / 'firmware-scanner/bin' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            self.copy_file(str(target / 'release' / name), str(destination))
            metadata = json.loads(subprocess.check_output([cargo, 'metadata', '--locked', '--format-version', '1',
                '--manifest-path', str(manifest)], cwd=root, text=True, encoding='utf8'))
            notices = []
            for package in metadata['packages']:
                directory = Path(package['manifest_path']).parent
                files = {p for pattern in ('LICENSE*', 'COPYING*', 'NOTICE*') for p in directory.glob(pattern) if p.is_file()}
                if package.get('license_file'):
                    declared = directory / package['license_file']
                    if declared.is_file():files.add(declared)
                relative = Path('licenses') / (package['name'] + '-' + package['version'])
                for source in sorted(files):
                    output = destination.parent / relative / source.name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    self.copy_file(str(source), str(output))
                notices.append({key:package.get(key) for key in ('name', 'version', 'license', 'repository')} |
                    {'files':[str(relative / p.name).replace('\\','/') for p in sorted(files)]})
            (destination.parent / 'THIRD-PARTY.json').write_text(json.dumps(notices, indent=2), encoding='utf8')

    def get_outputs(self, include_bytecode=True):
        outputs = super().get_outputs(include_bytecode)
        if not self.editable_mode:
            engine = Path(self.build_lib) / 'software_native/engine'
            generated = [str(p) for folder in ('dist', 'node_modules', 'firmware-scanner/bin')
                         for p in (engine / folder).rglob('*') if p.is_file()]
            outputs = list(dict.fromkeys([*outputs, *generated]))
        return outputs


class BdistWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = False

    def get_tag(self):
        _, _, platform = super().get_tag()
        return 'py3', 'none', platform
