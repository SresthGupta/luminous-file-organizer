from setuptools import setup, find_packages

setup(
    name="luminous-file-organizer",
    version="0.1.0",
    description="AI-powered file organizer using Claude Haiku",
    author="Luminous",
    python_requires=">=3.12",
    packages=find_packages(),
    install_requires=[
        "anthropic>=0.40.0",
        "typer[all]>=0.12.0",
        "rich>=13.0.0",
        "watchdog>=4.0.0",
        "PyYAML>=6.0",
        "PyMuPDF>=1.23.0",
        "Pillow>=10.0.0",
        "python-magic>=0.4.27",
        "rumps>=0.4.0",
    ],
    extras_require={
        "ocr": ["pytesseract>=0.3.10"],
    },
    entry_points={
        "console_scripts": [
            "luminous=src.cli:main",
            "luminous-gui=src.gui:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3.12",
        "Operating System :: MacOS",
        "Topic :: Utilities",
    ],
)
