from __future__ import annotations
from pathlib import Path
import msgspec
from niess.io.utils import encode_hook, decode_hook, Model, from_model


def to_json(obj) -> bytes:
    enc_hook = encode_hook(msgspec.json.Encoder())
    encoder = msgspec.json.Encoder(enc_hook=enc_hook)
    return encoder.encode(Model.from_value(obj, encoder=encoder))


def from_json(msg: bytes):
    from niess.io.utils import MODEL_DECODE
    decoded = msgspec.json.decode(msg, type=Model)

    dec_hook = decode_hook(msgspec.json.Decoder())
    ## FIXME The first (typed) version causes the TypeError
    ##       "unsupported operand type(s) for |: 'classmethod' and 'classmethod'"
    ##       _probably_ due to mccode_antlr.common.Expr using Union[...]
    ##       _without_ specifying to msgspec that its Structs should store type
    ##       information.
    # if decoded.name in MODEL_DECODE:
    #     decoder = msgspec.json.Decoder(MODEL_DECODE[decoded.name], dec_hook=dec_hook)
    # else:
    #     decoder = msgspec.json.Decoder(dec_hook=dec_hook)
    decoder = msgspec.json.Decoder(dec_hook=dec_hook)
    return from_model(decoder, decoded)


def save_json(obj, filename: str | Path) -> None:
    with open(filename, "wb") as f:
        f.write(to_json(obj))


def load_json(filename: str | Path):
    with open(filename, "rb") as f:
        return from_json(f.read())