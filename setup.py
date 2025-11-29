"""Setup for essayxblock XBlock."""

import os
from setuptools import setup


def package_data(pkg, roots):
    """Collect static and public files as package_data."""
    data = []
    for root in roots:
        for dirname, _, files in os.walk(os.path.join(pkg, root)):
            for fname in files:
                data.append(os.path.relpath(os.path.join(dirname, fname), pkg))
    return {pkg: data}


setup(
    name="essayxblock-xblock",   # distro name; can be anything unique
    version="0.2.0",
    description="AI-powered Essay XBlock with external backend scoring",
    packages=["essayxblock"],
    install_requires=[
        "XBlock",
        "web-fragments",
        "requests",
    ],
    entry_points={
        "xblock.v1": [
            # IMPORTANT: follow the same style as your working ptexblock:
            #   name = package.module:ClassName
            "essayxblock = essayxblock.essayxblock:EssayXBlock",
        ]
    },
    package_data=package_data("essayxblock", ["static", "public"]),
    include_package_data=True,
)
