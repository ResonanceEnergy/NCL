# setup.py
"""
Setup script for Neural Control Language (NCL)
"""

from setuptools import setup, find_packages
import os

# Read README
this_directory = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name="ncl-core",
    version="2.0.0",
    author="NCC Development Team",
    author_email="ncc@superagency.ai",
    description="Neural Control Language - Cyber-physical organism implementation",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ResonanceEnergy/Super-Agency",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: System :: Distributed Computing",
    ],
    python_requires=">=3.8",
    install_requires=[
        "asyncio-mqtt>=0.11.0",
        "pydantic>=2.0.0",
        "structlog>=23.0.0",
        "aiomqtt>=1.2.0",
        "cryptography>=41.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "mypy>=1.0.0",
            "flake8>=6.0.0",
        ],
        "monitoring": [
            "grafana-api>=1.0.3",
            "prometheus-client>=0.17.0",
        ],
        "security": [
            "bcrypt>=4.0.0",
            "pyjwt>=2.8.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "ncl-orchestrate=ncl.core.ncc:main",
            "ncl-monitor=ncl.monitoring.system_monitor:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
