# SPDX-FileCopyrightText: 2025-present Gregory Tucker <gregory.tucker@ess.eu>
#
# SPDX-License-Identifier: MIT

def test_primary_parameters():
    from textwrap import dedent
    from niess.bifrost.parameters import primary_parameters
    parameters = primary_parameters()

    names = list(parameters.keys())
    expected = dedent("""\
    source
    nboa_entry_window
    nboa
    nboa_exit_window
    monolith_window
    bbg_entry_window
    bbg
    bbg_exit_window
    psc_housing_entry_window
    nose
    pulse_shaping_chopper_1
    pulse_shaping_chopper_2
    unit_3_curved
    psc_exit_window
    psc_monitor
    curved_entrance_window
    unit_4_curved
    unit_4_exit_window
    frame_overlap_chopper_1
    unit_5_entry_window
    unit_5_curved
    unit_6_curved
    unit_7_curved
    unit_8_curved
    unit_8_exit_window
    frame_overlap_chopper_2
    unit_9_entry_window
    unit_9_curved
    unit_10_curved
    unit_11_curved
    unit_12_curved
    unit_13_curved
    unit_14_curved
    unit_15_curved
    unit_16_bw_insert
    unit_17_bw_insert
    unit_17_exit_window
    overlap_monitor
    unit_18_entry_window
    unit_18_expanding
    unit_19_expanding
    unit_20_expanding
    unit_21_expanding
    unit_22_expanding
    unit_23_expanding
    unit_24_expanding
    unit_25_expanding
    unit_26_expanding
    unit_27_expanding
    unit_28_expanding
    unit_28_exit_window
    unit_29_entry_window
    unit_29_straight
    unit_30_straight
    unit_31_straight
    unit_32_straight
    unit_33_straight
    unit_34_straight
    unit_35_straight
    unit_36_straight
    unit_37_straight
    unit_38_straight
    unit_39_straight
    unit_40_straight
    unit_41_straight
    unit_42_straight
    unit_43_straight
    bandwidth_chopper_1
    bandwidth_chopper_2
    unit_43_exit_window
    bandwidth_monitor
    unit_44_entry_window
    unit_44_straight
    unit_45_straight
    unit_46_straight
    unit_47_straight
    unit_48_straight
    unit_49_straight
    unit_50_straight
    unit_51_straight
    unit_52_straight
    unit_53_straight
    unit_54_straight
    unit_55_straight
    unit_56_straight
    unit_57_straight
    unit_58_straight
    unit_59_straight
    unit_60_straight
    unit_61_straight
    unit_62_straight
    unit_63_straight
    unit_64_straight
    unit_65_straight
    unit_66_straight
    unit_67_straight
    unit_68_straight
    unit_69_straight
    unit_70_straight
    unit_71_straight
    unit_72_straight
    unit_73_straight
    unit_74_straight
    unit_75_straight
    unit_76_closing
    unit_77_closing
    unit_78_closing
    unit_79_closing
    unit_80_closing
    unit_81_closing
    unit_82_closing
    unit_83_closing
    unit_84_closing
    unit_85_closing
    jaw_3
    unit_86_closing
    jaw_2
    unit_87_closing
    jaw_1
    unit_88_closing
    unit_88_exit_window
    mask
    normalization_monitor
    slit""").splitlines()

    print(names)
    for name, ex in zip(names, expected, strict=True):
        assert name == ex

    assert len(parameters) == len(expected)


