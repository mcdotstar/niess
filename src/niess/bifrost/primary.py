"""The BIFROST primary spectrometer contains components which are only passed in series.

To make it easier to comprehend and maintain, the spectrometer is broken up into a
series of sections, each of which performs a specific function.

Each section contains a mixture of guide elements, choppers, monitors, attenuators,
windows, etc.; but they all come together into the primary spectrometer.
"""
from ..components import (
    Section, Component,
    Jaw, Slit, Filter, Attenuator, DiscChopper,
    EllipticGuide, StraightGuide, StraightGuides, TaperedGuides,
    FissionChamber, BeamCurrentMonitor, GEM2D, ESSource
)
from ..utilities import calibration

PRIMARY_TYPES = {
    'source': ESSource,
    # compressor section
    'nboa_entry_window': Filter,
    'nboa': EllipticGuide,  # Neutron Beam Optics Assembly
    'nboa_exit_window': Filter,
    'monolith_window': Filter,
    'bbg_entry_window': Filter,
    'bbg': EllipticGuide,  # Bridge Beam Guide
    'bbg_exit_window': Filter,
    'psc_housing_entry_window': Filter,
    'nose': EllipticGuide,
    # pulse shaping choppers (not in a named section ...)
    'pulse_shaping_chopper_1': DiscChopper,
    'pulse_shaping_chopper_2': DiscChopper,
    # curved guide section
    'unit_3_curved': StraightGuides,
    'psc_exit_window': Filter,
    'psc_monitor': FissionChamber,
    'curved_entrance_window': Filter,
    'unit_4_curved': StraightGuides,
    'unit_4_exit_window': Filter,
    'frame_overlap_chopper_1': DiscChopper,
    'unit_5_entry_window': Filter,
    'unit_5_curved': StraightGuides,
    'unit_6_curved': StraightGuides,
    'unit_7_curved': StraightGuides,
    'unit_8_curved': StraightGuides,
    'unit_8_exit_window': Filter,
    'frame_overlap_chopper_2': DiscChopper,
    'unit_9_entry_window': Filter,
    'unit_9_curved': StraightGuides,
    'unit_10_curved': StraightGuides,
    'unit_11_curved': StraightGuides,
    'unit_12_curved': StraightGuides,
    'unit_13_curved': StraightGuides,
    'unit_14_curved': StraightGuides,
    'unit_15_curved': StraightGuides,
    # expanding guide section
    'unit_16_bw_insert': EllipticGuide,  # Bunker wall insert, first part
    'unit_17_bw_insert': EllipticGuide,  # Bunker wall insert, second part
    'unit_17_exit_window': Filter,
    'overlap_monitor': BeamCurrentMonitor,
    'unit_18_entry_window': Filter,
    'unit_18_expanding': EllipticGuide,
    'unit_19_expanding': EllipticGuide,
    'unit_20_expanding': EllipticGuide,
    'unit_21_expanding': EllipticGuide,
    'unit_22_expanding': EllipticGuide,
    'unit_23_expanding': EllipticGuide,
    'unit_24_expanding': EllipticGuide,
    'unit_25_expanding': EllipticGuide,
    'unit_26_expanding': EllipticGuide,
    'unit_27_expanding': EllipticGuide,
    'unit_28_expanding': EllipticGuide,
    'unit_28_exit_window': Filter,
    # straight guide transport section
    'unit_29_entry_window': Filter,
    'unit_29_straight': StraightGuide,
    'unit_30_straight': StraightGuide,
    'unit_31_straight': StraightGuide,
    'unit_32_straight': StraightGuide,
    'unit_33_straight': StraightGuide,
    'unit_34_straight': StraightGuide,
    'unit_35_straight': StraightGuide,
    'unit_36_straight': StraightGuide,
    'unit_37_straight': StraightGuide,
    'unit_38_straight': StraightGuide,
    'unit_39_straight': StraightGuide,
    'unit_40_straight': StraightGuide,
    'unit_41_straight': StraightGuide,
    'unit_42_straight': StraightGuide,
    'unit_43_straight': StraightGuide,
    'bandwidth_chopper_1': DiscChopper,
    'bandwidth_chopper_2': DiscChopper,
    'unit_43_exit_window': Filter,
    'bandwidth_monitor': BeamCurrentMonitor,
    'attenuator_1': Attenuator,
    'attenuator_2': Attenuator,
    'attenuator_3': Attenuator,
    'unit_44_entry_window': Filter,
    'unit_44_straight': StraightGuide,
    'unit_45_straight': StraightGuide,
    'unit_46_straight': StraightGuide,
    'unit_47_straight': StraightGuide,
    'unit_48_straight': StraightGuide,
    'unit_49_straight': StraightGuide,
    'unit_50_straight': StraightGuide,
    'unit_51_straight': StraightGuide,
    'unit_52_straight': StraightGuide,
    'unit_53_straight': StraightGuide,
    'unit_54_straight': StraightGuide,
    'unit_55_straight': StraightGuide,
    'unit_56_straight': StraightGuide,
    'unit_57_straight': StraightGuide,
    'unit_58_straight': StraightGuide,
    'unit_59_straight': StraightGuide,
    'unit_60_straight': StraightGuide,
    'unit_61_straight': StraightGuide,
    'unit_62_straight': StraightGuide,
    'unit_63_straight': StraightGuide,
    'unit_64_straight': StraightGuide,
    'unit_65_straight': StraightGuide,
    'unit_66_straight': StraightGuide,
    'unit_67_straight': StraightGuide,
    'unit_68_straight': StraightGuide,
    'unit_69_straight': StraightGuide,
    'unit_70_straight': StraightGuide,
    'unit_71_straight': StraightGuide,
    'unit_72_straight': StraightGuide,
    'unit_73_straight': StraightGuide,
    'unit_74_straight': StraightGuide,
    'unit_75_straight': StraightGuide,
    # focusing section
    'unit_76_closing': EllipticGuide,
    'unit_77_closing': EllipticGuide,
    'unit_78_closing': EllipticGuide,
    'unit_79_closing': EllipticGuide,
    'unit_80_closing': EllipticGuide,
    'unit_81_closing': EllipticGuide,
    'unit_82_closing': EllipticGuide,
    'unit_83_closing': EllipticGuide,
    'unit_84_closing': EllipticGuide,
    'unit_85_closing': EllipticGuide,
    'jaw_3': Jaw,
    'unit_86_closing': EllipticGuide,
    'jaw_2': Jaw,
    'unit_87_closing': EllipticGuide,
    'jaw_1': Jaw,
    'unit_88_closing': EllipticGuide,
    'unit_88_exit_window': Filter,
    'mask': Slit,
    'normalization_monitor': GEM2D,
    'slit': Slit,
    'sample_origin': Component,
}

class Primary(Section):
    __struct_field_types__ = PRIMARY_TYPES  # an inconvenient hack

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
    unit_31_straight: StraightGuide
    unit_32_straight: StraightGuide
    unit_33_straight: StraightGuide
    unit_34_straight: StraightGuide
    unit_35_straight: StraightGuide
    unit_36_straight: StraightGuide
    unit_37_straight: StraightGuide
    unit_38_straight: StraightGuide
    unit_39_straight: StraightGuide
    unit_40_straight: StraightGuide
    unit_41_straight: StraightGuide
    unit_42_straight: StraightGuide
    unit_43_straight: StraightGuide
    bandwidth_chopper_1: DiscChopper
    bandwidth_chopper_2: DiscChopper
    unit_43_exit_window: Filter
    bandwidth_monitor: BeamCurrentMonitor
    attenuator_1: Attenuator
    attenuator_2: Attenuator
    attenuator_3: Attenuator
    unit_44_entry_window: Filter
    #
    unit_44_straight: StraightGuide
    unit_45_straight: StraightGuide
    unit_46_straight: StraightGuide
    unit_47_straight: StraightGuide
    unit_48_straight: StraightGuide
    unit_49_straight: StraightGuide
    unit_50_straight: StraightGuide
    unit_51_straight: StraightGuide
    unit_52_straight: StraightGuide
    unit_53_straight: StraightGuide
    unit_54_straight: StraightGuide
    unit_55_straight: StraightGuide
    unit_56_straight: StraightGuide
    unit_57_straight: StraightGuide
    unit_58_straight: StraightGuide
    unit_59_straight: StraightGuide
    unit_60_straight: StraightGuide
    unit_61_straight: StraightGuide
    unit_62_straight: StraightGuide
    unit_63_straight: StraightGuide
    unit_64_straight: StraightGuide
    unit_65_straight: StraightGuide
    unit_66_straight: StraightGuide
    unit_67_straight: StraightGuide
    unit_68_straight: StraightGuide
    unit_69_straight: StraightGuide
    unit_70_straight: StraightGuide
    unit_71_straight: StraightGuide
    unit_72_straight: StraightGuide
    unit_73_straight: StraightGuide
    unit_74_straight: StraightGuide
    unit_75_straight: StraightGuide

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

    sample_origin: Component

    @classmethod
    @calibration
    def from_calibration(cls, parameters: dict):
        from .parameters import primary_parameters
        if len(parameters) == 0:
            parameters = primary_parameters()
        return super().from_calibration(parameters)


