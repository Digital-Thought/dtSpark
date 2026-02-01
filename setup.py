#!/usr/bin/env python3
"""
Setup script for Spark - Secure Personal AI Research Kit.

A multi-provider LLM CLI and Web interface with MCP tool integration.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding="utf-8")

# Read version from _version.txt
version_file = this_directory / "src" / "dtSpark" / "_version.txt"
version = version_file.read_text(encoding="utf-8").strip()

setup(
    name="dtSpark",
    version=version,
    author="Matthew Westwood-Hill",
    author_email="matthew@digital-thought.org",
    description="Secure Personal AI Research Kit - Multi-provider LLM CLI/Web interface with MCP tool integration",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/digital-thought/dtSpark",
    project_urls={
        "Bug Reports": "https://github.com/digital-thought/dtSpark/issues",
        "Source": "https://github.com/digital-thought/dtSpark",
        "Documentation": "https://github.com/digital-thought/dtSpark#readme",
    },
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "Intended Audience :: Information Technology",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Communications :: Chat",
    ],
    keywords=[
        "llm",
        "ai",
        "chatbot",
        "aws",
        "bedrock",
        "anthropic",
        "claude",
        "ollama",
        "mcp",
        "model-context-protocol",
        "cli",
        "web",
    ],
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    include_package_data=True,
    package_data={
        "dtSpark": [
            "_*.txt",
            "_*.yaml",
            "resources/*.yaml",
            "resources/*.template",
            "web/templates/*.html",
            "web/static/css/*.css",
            "web/static/js/*.js",
        ],
    },
    python_requires=">=3.10",
    install_requires=[
        # AWS SDK
        "boto3>=1.28.0",
        "botocore>=1.31.0",
        # Web framework
        "fastapi>=0.100.0",
        "uvicorn>=0.22.0",
        "jinja2>=3.1.0",
        "python-multipart>=0.0.6",
        "sse-starlette>=1.6.0",
        # CLI interface
        "rich>=13.0.0",
        "prompt_toolkit>=3.0.0",
        # HTTP client
        "httpx>=0.24.0",
        "aiohttp>=3.8.0",
        # MCP (Model Context Protocol)
        "mcp>=0.9.0",
        # Data handling
        "pyyaml>=6.0",
        # Application framework
        "dtPyAppFramework>=4.2.1",
        # Cryptography for SSL
        "cryptography>=41.0.0",
        # Anthropic direct API (optional but commonly used)
        "anthropic>=0.18.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.0.0",
            "black>=23.0.0",
            "isort>=5.12.0",
            "mypy>=1.0.0",
            "flake8>=6.0.0",
        ],
        "mysql": [
            "mysql-connector-python>=8.0.0",
        ],
        "postgresql": [
            "psycopg2-binary>=2.9.0",
        ],
        "mssql": [
            "pyodbc>=4.0.0",
        ],
        "all-databases": [
            "mysql-connector-python>=8.0.0",
            "psycopg2-binary>=2.9.0",
            "pyodbc>=4.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "spark=dtSpark.launch:main",
            "dtSpark=dtSpark.launch:main"
        ],
    },
    zip_safe=False,
)
