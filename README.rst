``rstviewer`` is a simple program for editing a reStructuredText (RST) file.
In fact, it's being used to edit this file right now!

Usage
-----
Executing

.. code:: bash

    $ rstviewer file.rst

opens a new browser window containing an HTML representation of of
``file.rst``. The browser window refreshes when ``file.rst`` is changed.

Requirements
------------
Python 3.5 or greater and a browser which supports WebSockets.

Author
------
Jonathan Terhorst <terhorst@gmail.com>

Inspiration
-----------
NPM package |rst-live-preview|_, which I could not get running.

.. |rst-live-preview| replace:: ``rst-live-preview``
.. _rst-live-preview: https://github.com/frantic1048/rst-live-preview
