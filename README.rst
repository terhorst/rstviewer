``rstviewer`` is a simple program for editing a reStructuredText (RST) file.
In fact, it's being used to edit this file right now!

Usage
-----
Executing

.. code:: bash

    $ rstviewer file.rst

opens a new browser window containing an HTML representation of of
``file.rst``. The browser window refreshes when ``file.rst`` is changed.

Options
-------

By default, ``rstviewer`` runs in quiet mode -- no logging messages are
emitted, so as not to interfere with editing in the console. The option
``-v``, which can be specified multiple times, increases the verbosity
level.

Security
--------
Practically nonexistent. The program creates an HTTP server which serves
all files located in or beneath the directory containing ``file.rst``.
This is to facilitate the loading of images and other assets linked by
the RST document. Although the server binds only to the local interface,
this is still insecure. In short, do not use this program if you are
concerned about security.

Requirements
------------
Python 3.6+ and a browser which supports WebSockets. (The package has
been tested only on Chrome and Safari, thus far.)

Author
------
Jonathan Terhorst <terhorst@gmail.com>

Inspiration
-----------
NPM package |rst-live-preview|_, which I could not get running.

.. |rst-live-preview| replace:: ``rst-live-preview``
.. _rst-live-preview: https://github.com/frantic1048/rst-live-preview
