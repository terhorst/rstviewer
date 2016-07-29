from setuptools import setup

setup(
        name = "rstviewer",
        version = "0.0.1",
        author = "Jonathan Terhorst",
        author_email = "terhorst@gmail.com",
        description = "An in-browser RST viewer with live updating",
        license = "BSD",
        keywords = "ReStructuredText rst editor viewer",
        packages = ['rstviewer'],
        install_requires=[
            'rst2html5',
            'hachiko',
            'watchdog',
            'aiohttp'],
        entry_points={
            'console_scripts': [
                'rstviewer = rstviewer.rstviewer:main'
                ]})
