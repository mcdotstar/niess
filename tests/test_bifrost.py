# SPDX-FileCopyrightText: 2025-present Gregory Tucker <gregory.tucker@ess.eu>
#
# SPDX-License-Identifier: MIT


def get_mccode_registries():
    # from subprocess import run
    from mccode_antlr.reader import MCSTAS_REGISTRY, GitHubRegistry #, LocalRegistry

    registries = ['mcstas-chopper-lib', 'mcstas-transformer', 'mcstas-detector-tubes',
                  'mcstas-epics-link', 'mcstas-frame-tof-monitor', 'mccode-mcpl-filter',
                  'mcstas-monochromator-rowland', 'mcstas-slit-radial']
    registries = [GitHubRegistry(
        name,
        url=f'https://github.com/mcdotstar/{name}',
        filename='pooch-registry.txt',
        version='main'
    ) for name in registries]

    # r = run(['readout-config', '--show', 'compdir'], check=True, capture_output=True, text=True)
    # readout_registry = LocalRegistry(name='readout', root=r.stdout.strip())

    return [MCSTAS_REGISTRY] + registries # + [readout_registry]



def test_bifrost_whole():
    from niess.bifrost.parameters import primary_parameters
    from niess.bifrost.parameters import known_channel_params
    from niess.bifrost import Tank, Primary

    primary = Primary.from_calibration(primary_parameters())
    tank = Tank.from_calibration(**known_channel_params())


def test_bifrost_mccode():
    from niess.bifrost.parameters import primary_parameters
    from niess.bifrost.parameters import known_channel_params
    from niess.bifrost import Tank, Primary
    from mccode_antlr.assembler import Assembler

    bifrost = Assembler('bifrost', registries=get_mccode_registries())

    primary = Primary.from_calibration(primary_parameters())
    primary.to_mccode(bifrost)

    # TODO insert pre- and post-sample things here
    #      e.g., the split_at location at the end of the guide
    #      any filters, e.g., a hits-the-sample MCPL filter, or a Be-transmission filter
    #      the radial collimator between sample and tank, etc.

    tank = Tank.from_calibration(**known_channel_params())
    tank.to_mccode(bifrost, 'sample_origin')

    # TODO add checks that conversion from the intermediate representation works?
