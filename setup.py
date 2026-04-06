from __future__ import annotations

from pathlib import Path

from setuptools import setup


ROOT = Path(__file__).resolve().parent


def read_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


setup(
    name="astroview",
    version=read_text("VERSION").strip(),
    description="A desktop FITS astronomical image viewer built with PySide6.",
    long_description=read_text("README.md"),
    long_description_content_type="text/markdown",
    author="Fitson",
    license="MIT",
    python_requires=">=3.10",
    install_requires=[
        "PySide6>=6.5",
        "astropy>=5.3",
        "numpy>=1.24",
        "sep>=1.2",
    ],
    package_dir={
        "astroview": ".",
        "astroview.app": "app",
        "astroview.core": "core",
    },
    packages=[
        "astroview",
        "astroview.app",
        "astroview.core",
    ],
    package_data={
        "astroview": [
            "resources/icons/*.ico",
            "resources/icons/*.png",
            "VERSION",
        ],
    },
    include_package_data=True,
    entry_points={
        "console_scripts": [
            "astroview=astroview.main:main",
        ],
    },
)
