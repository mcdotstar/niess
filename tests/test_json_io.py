import scipp as sc


def scipp_round_trip(variable):
    import msgspec
    from niess.io.scipp import ScippModel, from_scipp_model
    encoder = msgspec.json.Encoder()
    modeled = ScippModel.from_value(variable, encoder=encoder)
    json = encoder.encode(modeled)

    decoded = msgspec.json.decode(json, type=ScippModel)
    assert modeled == decoded
    return from_scipp_model(msgspec.json.Decoder(), decoded)


def niess_round_trip(value):
    import msgspec
    from niess.io.utils import Model, from_model, decode_hook, MODEL_DECODE
    from niess.io.utils import encode_hook
    encoder = msgspec.json.Encoder(enc_hook=encode_hook(msgspec.json.Encoder()))
    modeled = Model.from_value(value, encoder=encoder)
    json = encoder.encode(modeled)
    decoded = msgspec.json.decode(json, type=Model)
    assert modeled == decoded
    dec_hook = decode_hook(msgspec.json.Decoder())
    decoder = msgspec.json.Decoder(dec_hook=dec_hook)
    return from_model(decoder, decoded)


def test_scipp_scalar():
    p = sc.scalar(3.14159, unit='rad')
    assert p == scipp_round_trip(p)

def test_scipp_vector():
    p = sc.vector([1,2,3.], unit='m')
    assert p == scipp_round_trip(p)


def test_scipp_rotation():
    q = sc.spatial.rotation(value=[0,0,0,1.])
    assert q == scipp_round_trip(q)


def test_scipp_array():
    from numpy.random import random
    a = sc.array(values=random((10,20)), variances=random((10,20)), dims=['a', 'b'], unit='m')
    res = scipp_round_trip(a)
    assert sc.allclose(res, a)


def test_mccode_types():
    from mccode_antlr.common.parameters import InstrumentParameter
    par = InstrumentParameter.parse('int named/"K" = -1')
    print(par)
    assert par.name == 'named'
    assert par.unit == '"K"'
    assert par.value.value == -1
    ret = niess_round_trip(par)
    assert par == ret


def test_fake_niess_component():
    from niess.components import He3Monitor
    from pytest import raises
    from msgspec import ValidationError
    b = He3Monitor(
        name='mon1',
        position=[1,2,3],
        orientation=[0,0,0,1],
        radius=10,
        length=20,
        pressure=1
    )
    # If the decoder used the typed variant, this would fail ... but other
    # types wouldn't decode since they include McCode_antlr objects ...
    # # Fails due to the incorrect data types provided
    # with raises(ValidationError):
    #     niess_round_trip(b)
    assert b == niess_round_trip(b)


def test_niess_component():
    from niess.components import He3Monitor
    import scipp as sc
    b = He3Monitor(
        name='mon2',
        position=sc.vector([1, 2, 3], unit='m'),
        orientation=sc.spatial.rotation(value=[0, 0, 0, 1]),
        radius=sc.scalar(10., unit='mm'),
        length=sc.scalar(20, unit='mm'),
        pressure=sc.scalar('1', unit='atm')
    )
    assert b == niess_round_trip(b)


def test_niess_source():
    from niess.components import ESSource
    source = ESSource.from_calibration(
        dict(wavelength_minimum='double minimum/"angstrom"=1.0',)
    )
    assert source == niess_round_trip(source)


def test_section():
    from niess.components import Section
    section = Section()
    returned = niess_round_trip(section)
    assert section == returned


def test_bifrost_primary():
    from niess.bifrost.parameters import primary_parameters
    from niess.bifrost import Primary
    primary = Primary.from_calibration(primary_parameters())
    assert primary == primary
    returned = niess_round_trip(primary)
    assert primary == returned


def test_bifrost_tank():
    from niess.bifrost.parameters import tank_parameters
    from niess.bifrost import Tank
    tank = Tank.from_calibration(tank_parameters())
    assert tank == tank
    returned = niess_round_trip(tank)
    assert tank == returned