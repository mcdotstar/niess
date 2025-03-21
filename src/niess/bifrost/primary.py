"""The BIFROST primary spectrometer contains components which are only passed in series.

To make it easier to comprehend and maintain, the spectrometer is broken up into a
series of sections, each of which performs a specific function.

Each section contains a mixture of guide elements, choppers, monitors, attenuators,
windows, etc.; but they all come together into the primary spectrometer.
"""
from dataclasses import dataclass
from ..components import (
    Section,
    Jaw, Slit, Filter, DiscChopper,
    EllipticGuide, StraightGuide, StraightGuides, TaperedGuides,
    FissionChamber, BeamCurrentMonitor, GEM2D, ESSource
)

@dataclass
class Primary(Section):
    source: ESSource

    # compressor section
    nboa_entry_window: Filter
    nboa: EllipticGuide  # Neutron Beam Optics Assembly
    nboa_exit_window: Filter
    monolith_window: Filter
    bbg_entry_window: Filter
    bbg: EllipticGuide  # Bridge Beam Guide
    bbg_exit_window: Filter
    psc_housing_entry_window: Filter
    nose: EllipticGuide

    # pulse shaping choppers (not in a named section ...)
    pulse_shaping_chopper_1: DiscChopper
    pulse_shaping_chopper_2: DiscChopper

    # curved guide section
    unit_3_curved: StraightGuides
    psc_exit_window: Filter
    psc_monitor: FissionChamber
    curved_entrance_window: Filter
    unit_4_curved: StraightGuides
    unit_4_exit_window: Filter
    frame_overlap_chopper_1: DiscChopper
    unit_5_entry_window: Filter
    unit_5_curved: StraightGuides
    unit_6_curved: StraightGuides
    unit_7_curved: StraightGuides
    unit_8_curved: StraightGuides
    unit_8_exit_window: Filter
    frame_overlap_chopper_2: DiscChopper
    unit_9_entry_window: Filter
    unit_9_curved: StraightGuides
    unit_10_curved: StraightGuides
    unit_11_curved: StraightGuides
    unit_12_curved: StraightGuides
    unit_13_curved: StraightGuides
    unit_14_curved: StraightGuides
    unit_15_curved: StraightGuides

    # expanding guide section
    unit_16_bw_insert: EllipticGuide  # Bunker wall insert, first part
    unit_17_bw_insert: EllipticGuide  # Bunker wall insert, second part
    unit_17_exit_window: Filter
    overlap_monitor: BeamCurrentMonitor
    unit_18_entry_window: Filter
    unit_18_expanding: EllipticGuide
    unit_19_expanding: EllipticGuide
    unit_20_expanding: EllipticGuide
    unit_21_expanding: EllipticGuide
    unit_22_expanding: EllipticGuide
    unit_23_expanding: EllipticGuide
    unit_24_expanding: EllipticGuide
    unit_25_expanding: EllipticGuide
    unit_26_expanding: EllipticGuide
    unit_27_expanding: EllipticGuide
    unit_28_expanding: EllipticGuide
    unit_28_exit_window: Filter

    # straight guide transport section
    unit_29_entry_window: Filter
    unit_29_straight: StraightGuide
    unit_30_straight: StraightGuide
    unit_31_straight: StraightGuides
    unit_32_straight: StraightGuides
    unit_33_straight: StraightGuides
    unit_34_straight: StraightGuides
    unit_35_straight: StraightGuides
    unit_36_straight: StraightGuides
    unit_37_straight: StraightGuides
    unit_38_straight: StraightGuides
    unit_39_straight: StraightGuides
    unit_40_straight: StraightGuides
    unit_41_straight: StraightGuides
    unit_42_straight: StraightGuides
    unit_43_straight: StraightGuides
    bandwidth_chopper_1: DiscChopper
    bandwidth_chopper_2: DiscChopper
    unit_43_exit_window: Filter
    bandwidth_monitor: BeamCurrentMonitor
    unit_44_entry_window: Filter
    #
    unit_44_straight: StraightGuides
    unit_45_straight: StraightGuides
    unit_46_straight: StraightGuides
    unit_47_straight: StraightGuides
    unit_48_straight: StraightGuides
    unit_49_straight: StraightGuides
    unit_50_straight: StraightGuides
    unit_51_straight: StraightGuides
    unit_52_straight: StraightGuides
    unit_53_straight: StraightGuides
    unit_54_straight: StraightGuides
    unit_55_straight: StraightGuides
    unit_56_straight: StraightGuides
    unit_57_straight: StraightGuides
    unit_58_straight: StraightGuides
    unit_59_straight: StraightGuides
    unit_60_straight: StraightGuides
    unit_61_straight: StraightGuides
    unit_62_straight: StraightGuides
    unit_63_straight: StraightGuides
    unit_64_straight: StraightGuides
    unit_65_straight: StraightGuides
    unit_66_straight: StraightGuides
    unit_67_straight: StraightGuides
    unit_68_straight: StraightGuides
    unit_69_straight: StraightGuides
    unit_70_straight: StraightGuides
    unit_71_straight: StraightGuides
    unit_72_straight: StraightGuides
    unit_73_straight: StraightGuides
    unit_74_straight: StraightGuides
    unit_75_straight: StraightGuides

    # focusing section
    unit_76_closing: EllipticGuide
    unit_77_closing: EllipticGuide
    unit_78_closing: EllipticGuide
    unit_79_closing: EllipticGuide
    unit_80_closing: EllipticGuide
    unit_81_closing: EllipticGuide
    unit_82_closing: EllipticGuide
    unit_83_closing: EllipticGuide
    unit_84_closing: EllipticGuide
    unit_85_closing: EllipticGuide
    jaw_3: Jaw
    unit_86_closing: EllipticGuide
    jaw_2: Jaw
    unit_87_closing: EllipticGuide
    jaw_1: Jaw
    unit_88_closing: EllipticGuide
    unit_88_exit_window: Filter
    mask: Slit
    normalization_monitor: GEM2D
    slit: Slit



