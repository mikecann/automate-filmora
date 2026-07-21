"""Compatibility metadata for older setuptools used by the macOS system Python."""

from setuptools import find_packages, setup


setup(
    name="automate-filmora",
    version="0.13.7",
    description="Inspect and safely automate Wondershare Filmora project files",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    packages=find_packages(include=["filmora_wfp", "filmora_wfp.*"]),
    python_requires=">=3.9",
    entry_points={"console_scripts": ["filmora-project=filmora_wfp.cli:main"]},
)
