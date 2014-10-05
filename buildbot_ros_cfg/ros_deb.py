from buildbot.config import BuilderConfig
from buildbot.process.factory import BuildFactory
from buildbot.process.properties import Interpolate
from buildbot.steps.source.git import Git
from buildbot.steps.shell import ShellCommand, SetPropertyFromCommand
from buildbot.steps.transfer import FileUpload, FileDownload
from buildbot.steps.trigger import Trigger
from buildbot.steps.master import MasterShellCommand
from buildbot.steps.slave import RemoveDirectory
from buildbot.schedulers import triggerable

from helpers import success

## @brief Debbuilds are used for building sourcedebs & binaries out of gbps and uploading to an APT repository
## @param c The Buildmasterconfig
## @param job_name Name for this job (typically the metapackage name)
## @param packages List of packages to build.
## @param url URL of the BLOOM repository.
## @param distro Ubuntu distro to build for (for instance, 'precise')
## @param arch Architecture to build for (for instance, 'amd64')
## @param rosdistro ROS distro (for instance, 'groovy')
## @param version Release version to build (for instance, '0.8.1-0')
## @param machines List of machines this can build on.
## @param othermirror Cowbuilder othermirror parameter
## @param keys List of keys that cowbuilder will need
## @param trigger_pkgs List of packages names to trigger after our build is done.
def ros_debbuild(c, job_name, packages, url, distro, arch, rosdistro, version, machines, othermirror, keys, trigger_pkgs = None):
    gbp_args = ['-uc', '-us', '--git-ignore-branch', '--git-ignore-new',
                '--git-verbose', '--git-dist='+distro, '--git-arch='+arch]
    f = BuildFactory()
    # Remove the build directory.
    f.addStep(
        RemoveDirectory(
            name = job_name+'-clean',
            dir = Interpolate('%(prop:workdir)s'),
            hideStepIf = success,
        )
    )
    # Check out the repository master branch, since releases are tagged and not branched
    f.addStep(
        Git(
            repourl = url,
            branch = 'master',
            alwaysUseLatest = True, # this avoids broken builds when schedulers send wrong tag/rev
            mode = 'full' # clean out old versions
        )
    )
    # Update the cowbuilder
    f.addStep(
        ShellCommand(
            command = ['cowbuilder-update.py', distro, arch] + keys,
            hideStepIf = success,
            # TODO: We shouldn't have to explicitly specify this. This path is
            # already exported in the slave's .profile file.
            env = { 'PATH': [ '/home/buildbot_slave/buildbot-ros/scripts', '${PATH}' ] },
        )
    )
    # Need to build each package in order
    for package in packages:
        # TODO: Automatically determine if this is a third-party package.
        is_catkin = package not in [ 'boost_numpy', 'boost_numpy_eigen', 'openrave' ]
        if is_catkin:
            debian_pkg = 'ros-' + rosdistro + '-' + package.replace('_','-')
        else:
            debian_pkg = package.replace('_','-')

        branch_name = 'debian/'+debian_pkg+'_%(prop:release_version)s_'+distro  # release branch from bloom
        deb_name = debian_pkg+'_%(prop:release_version)s'+distro

        final_name = debian_pkg+'_%(prop:release_version)s-%(prop:datestamp)s'+distro+'_'+arch+'.deb'
        # Check out the proper tag. Use --force to delete changes from previous deb stamping
        f.addStep(
            ShellCommand(
                haltOnFailure = True,
                name = package+'-checkout',
                command = ['git', 'checkout', Interpolate(branch_name), '--force'],
                hideStepIf = success
            )
        )
        # Build the source deb
        f.addStep(
            ShellCommand(
                haltOnFailure = True,
                name = package+'-buildsource',
                command = ['git-buildpackage', '-S'] + gbp_args,
                descriptionDone = ['sourcedeb', package]
            )
        )
        # Upload sourcedeb to master.
        dsc_name = debian_pkg+'_%(prop:partial_version)s'
        f.addStep(
            FileUpload(
                name = package+'-uploadsource-orig',
                slavesrc = Interpolate('%(prop:workdir)s/'+dsc_name+'.orig.tar.gz'),
                masterdest = Interpolate('sourcedebs/'+dsc_name+'.orig.tar.gz'),
                hideStepIf = success,
                mode = 0644,
            )
        )
        f.addStep(
            FileUpload(
                name = package+'-uploadsource-tar',
                slavesrc = Interpolate('%(prop:workdir)s/'+deb_name+'.debian.tar.gz'),
                masterdest = Interpolate('sourcedebs/'+deb_name+'.debian.tar.gz'),
                hideStepIf = success,
                mode = 0644,
            )
        )
        f.addStep(
            FileUpload(
                name = package+'-uploadsource-dsc',
                slavesrc = Interpolate('%(prop:workdir)s/'+deb_name+'.dsc'),
                masterdest = Interpolate('sourcedebs/'+deb_name+'.dsc'),
                mode = 0644,
            )
        )
        # Stamp the changelog, in a similar fashion to the ROS buildfarm
        f.addStep(
            SetPropertyFromCommand(
                command="date +%Y%m%d-%H%M-%z", property="datestamp",
                name = package+'-getstamp',
                hideStepIf = success
            )
        )
        f.addStep(
            ShellCommand(
                haltOnFailure = True,
                name = package+'-stampdeb',
                command = ['git-dch', '-a', '--ignore-branch', '--verbose',
                           '-N', Interpolate('%(prop:release_version)s-%(prop:datestamp)s'+distro)],
                descriptionDone = ['stamped changelog', Interpolate('%(prop:release_version)s'),
                                   Interpolate('%(prop:datestamp)s')]
            )
        )
        # download hooks
        f.addStep(
            FileDownload(
                name = package+'-grab-hooks',
                mastersrc = 'hooks/D05deps',
                slavedest = Interpolate('%(prop:workdir)s/hooks/D05deps'),
                hideStepIf = success,
                mode = 0777 # make this executable for the cowbuilder
            )
        )
        # build the binary from the git working copy
        f.addStep(
            ShellCommand(
                haltOnFailure = True,
                name = package+'-buildbinary',
                command = ['git-buildpackage', '--git-pbuilder', '--git-export=WC',
                           Interpolate('--git-export-dir=%(prop:workdir)s')] + gbp_args,
                env = {'DIST': distro,
                       'GIT_PBUILDER_OPTIONS': Interpolate('--hookdir %(prop:workdir)s/hooks --override-config'),
                       'OTHERMIRROR': othermirror },
                descriptionDone = ['binarydeb', package]
            )
        )
        # Upload binarydeb to master
	# TODO: Decide where to put the package depending upon whether it is
	# public or private.
        f.addStep(
            FileUpload(
                name = package+'-uploadbinary',
                slavesrc = Interpolate('%(prop:workdir)s/'+final_name),
                masterdest = Interpolate('binarydebs/'+final_name),
                hideStepIf = success,
                mode = 0644,
            )
        )
        # Add the packages using reprepro updater script on master
        f.addStep(
            MasterShellCommand(
                name = package+'-includedeb',
                command = ['./scripts/aptly-include.sh', debian_pkg,
                           Interpolate('binarydebs/'+final_name), distro, arch ],
                descriptionDone = ['updated deb in apt', package]
            )
        )
        f.addStep(
            MasterShellCommand(
                name = package+'-includedsc',
                command = ['./scripts/aptly-include.sh', debian_pkg,
                           Interpolate('sourcedebs/'+deb_name+'.dsc'), distro, arch ],
                descriptionDone = ['updated dsc in apt', package]
            )
        )
    """
    # Trigger if needed
    if trigger_pkgs != None:
        f.addStep(
            Trigger(
                schedulerNames = [t.replace('_','-')+'-'+rosdistro+'-'+distro+'-'+arch+'-debtrigger' for t in trigger_pkgs],
                waitForFinish = False,
                alwaysRun=True
            )
        )
    """
    # Create trigger
    c['schedulers'].append(
        triggerable.Triggerable(
            name = job_name.replace('_','-')+'-'+rosdistro+'-'+distro+'-'+arch+'-debtrigger',
            builderNames = [job_name+'_'+rosdistro+'_'+distro+'_'+arch+'_debbuild',]
        )
    )
    # Add to builders
    partial_version, _, _ = version.partition('-')
    c['builders'].append(
        BuilderConfig(
            name = job_name+'_'+rosdistro+'_'+distro+'_'+arch+'_debbuild',
            properties = {'release_version' : version,
                          'partial_version' : partial_version,},
            slavenames = machines,
            factory = f
        )
    )
    # return name of builder created
    return job_name+'_'+rosdistro+'_'+distro+'_'+arch+'_debbuild'
