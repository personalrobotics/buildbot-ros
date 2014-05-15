#!/usr/bin/env python
from __future__ import print_function
import argparse, pwd, grp, os, shutil

BASE_INCOMING = '/var/www/packages/incoming/private'
APT_GID = pwd.getpwnam('debarchiver').pw_uid

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('package_name', type=str, help='Debian package name (e.g. ros-hydro-herbpy)')
    parser.add_argument('deb_path', type=str, help='path to the .deb file')
    parser.add_argument('distro', type=str, help='package distribution (e.g. precise)')
    parser.add_argument('arch', type=str, help='package architecture (e.g. amd64)')
    args = parser.parse_args()

    incoming_path = os.path.join(BASE_INCOMING, args.distro)
    print("Moving package '{:s}' into incoming queue '{:s}'.".format(args.package_name, incoming_path))
    os.chmod(args.deb_path, 0666)
    shutil.move(args.deb_path, incoming_path)
