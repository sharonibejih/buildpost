from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="buildpost",
    version="0.1.2",
    author="BuildPost Team",
    author_email="ebulamicheal@gmail.com",
    description="Turn your git commits into social media posts using AI",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/sharonibejih/buildpost",
    project_urls={
        "Bug Reports": "https://github.com/sharonibejih/buildpost/issues",
        "Source": "https://github.com/sharonibejih/buildpost",
    },
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Version Control :: Git",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=[
        "click>=8.0.0",
        "gitpython>=3.1.0",
        "pyyaml>=6.0",
        "openai>=1.0.0",
        "groq>=0.8.0",
        "pyperclip>=1.8.0",
        "colorama>=0.4.6",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "buildpost=buildpost.cli:main",
        ],
    },
    include_package_data=True,
    package_data={
        "buildpost": ["templates/*.yaml"],
    },
)
