OpenTTD Buildout
================

A buildout configuration for building openttd including
required resources (GFX, SFX, MSX) from source. The installation
is completely isolated and everything is done within the
repository directory.


Configurations
--------------

Main buildout configurations:

:server.cfg:
    Builds openttd in dedicated mode for running
    on servers. Installs supervisor and a controller script.

:macos.cfg: Client installation for Mac OS X.

Basis buildout configurations:

:base.cfg: Base buildout, building openttd and installing resources.

:version.cfg: Version pinnings.


Usage
-----

* Clone the git repository
* Symlink a main buildout configuration (e.g. *macos.cfg*) to *buildout.cfg*:
  ``ln -s macos.cfg buildout.cfg``
* Bootstrap buildout: ``python2.6 bootstrap.py``
* Run buildout: ``bin/buildout``
* Start openttd: ``bin/openttd``


The default config file will be generated at first openttd startup at
``[buildout-directory]var/personal/buildout.cfg``.


Links
-----

* http://www.openttd.org/
