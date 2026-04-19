from setuptools import setup, find_packages

setup(
    name="scPSS",
    version="0.1.1",
    author="Samin Rahman Khan",
    author_email="saminrk@iict.buet.ac.bd",
    description="single cell Pathological Shift Scoring",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/SaminRK/scPSS",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3.11",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.11",
    install_requires=[
        "numpy",
        "pandas",
        "scanpy==1.11.1",
        "anndata==0.10.3",
        "harmonypy",
        "kneed",
        "matplotlib",
    ],
)
