# SPDX-FileCopyrightText: 2025-present Gregory Tucker <gregory.tucker@ess.eu>
#
# SPDX-License-Identifier: MIT
"""Build a neutron instrument once, and convert it to whatever needs it.

Nothing is re-exported here: every import names its subject, so a reader can tell what
a line reaches for without knowing what this file happens to have collected.

    from niess.instrument import Instrument, Mount   # what an instrument is
    from niess.components import Crystal, He3Tube    # what it is made of
    from niess.mccode import to_mccode               # McStas .instr
    from niess.nexus import to_nexus_structure       # NeXus Structure JSON
    from niess.brep import save_step                 # STEP/CAD geometry
    from niess.tof import to_tof_model               # a chopper cascade diagram

Keeping this empty also keeps `import niess` cheap: it used to pull in the CAD target and
every component class to publish eleven names, three of which pointed at the older of two
implementations.
"""
