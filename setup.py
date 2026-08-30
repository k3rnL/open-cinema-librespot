from __future__ import annotations

import platform
import shutil
from pathlib import Path

from setuptools import Distribution, setup
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel

ROOT = Path(__file__).parent.resolve()
ARCHITECTURES = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64", "aarch64": "aarch64"}


class BuildPlugin(build_py):
    def run(self) -> None:
        super().run()
        target = Path(self.build_lib) / "open_cinema_librespot" / "runtime_assets"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            ROOT / "option-contract" / "librespot-v0.8.0.json",
            target / "option-contract.json",
        )


class PlatformDistribution(Distribution):
    def has_ext_modules(self) -> bool:
        # The package carries native executables rather than an extension module.
        # Declaring platform content keeps it in platlib and produces a platform wheel.
        return True


class PlatformWheel(bdist_wheel):
    def run(self) -> None:
        architecture = ARCHITECTURES.get(platform.machine().lower())
        if architecture is None:
            raise RuntimeError(f"unsupported wheel architecture: {platform.machine()}")
        directory = ROOT / "open_cinema_librespot" / "runtime_assets" / "bin" / architecture
        missing = [
            str(directory / name)
            for name in ("librespot", "open-cinema-librespot-oauth")
            if not (directory / name).is_file()
        ]
        if missing:
            raise RuntimeError(
                "platform wheel requires prebuilt verified assets; run "
                f"scripts/build_runtime_assets.py first (missing: {', '.join(missing)})"
            )
        super().run()

    def get_tag(self) -> tuple[str, str, str]:
        architecture = ARCHITECTURES[platform.machine().lower()]
        return "py3", "none", f"linux_{architecture}"


setup(
    cmdclass={"build_py": BuildPlugin, "bdist_wheel": PlatformWheel},
    distclass=PlatformDistribution,
)
