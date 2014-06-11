#!/bin/sh -e
package_name="$1"
deb_path="$2"
distro="$3"
architecture="$4"
repository="private"

sudo -Hu www-data -- /var/www/packages/aptly-add-package.bash "${repository}" "${distro}" "${deb_path}"
rm "${deb_path}"
