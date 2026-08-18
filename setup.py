"""Compatibility metadata for older setuptools used by the macOS system Python."""

from setuptools import find_packages, setup


setup(
    name="automate-filmora",
    version="0.13.9",
    description="Inspect and safely automate Wondershare Filmora project files",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Mike Cann",
    url="https://github.com/mikecann/automate-filmora",
    project_urls={
        "Documentation": "https://github.com/mikecann/automate-filmora#readme",
        "Issues": "https://github.com/mikecann/automate-filmora/issues",
        "Source": "https://github.com/mikecann/automate-filmora",
    },
    license="MIT",
    license_files=["LICENSE"],
    packages=find_packages(include=["filmora_wfp", "filmora_wfp.*"]),
    python_requires=">=3.9",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Multimedia :: Video",
    ],
    entry_points={"console_scripts": ["filmora-project=filmora_wfp.cli:main"]},
)
