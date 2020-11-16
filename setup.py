from setuptools import setup

setup(
    name="rstviewer",
    author="Jonathan Terhorst",
    author_email="terhorst@gmail.com",
    description="An in-browser RST viewer with live updating",
    license="GPL",
    url="https://github.com/terhorst/rstviewer",
    keywords="reStructuredText rst editor viewer",
    packages=["rstviewer"],
    use_scm_version=True,
    setup_requires=["setuptools_scm"],
    python_requires=">=3.6",
    install_requires=["rst2html5", "hachiko", "watchdog", "aiohttp>=3.7.2"],
    entry_points={
        "console_scripts": ["rstviewer = rstviewer.rstviewer:main"],
    },
    long_description=open("README.rst", "rt").read(),
)
