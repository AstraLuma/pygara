from dataclasses import dataclass
from enum import Enum
import io

import cbor2


FIELD_SEPEARATOR = b"\0"


def decoder(data: bytes):
    return cbor2.CBORDecoder(io.BytesIO(data))


def decode_cbor_uint(data: bytes) -> int:
    return decoder(data).decode()


@dataclass
class PathKey:
    path: bytes

    @classmethod
    def from_data(cls, data: bytes):
        # data is a filesystem path
        return cls(path=data)

    @staticmethod
    def decode_value(data: bytes):
        return cbor2.loads(data)


@dataclass
class DataKey:
    track_id: int

    @classmethod
    def from_data(cls, data: bytes):
        # print(f"{data=}")
        # data is a cbor uint
        return cls(track_id=cbor2.loads(data))

    @staticmethod
    def decode_value(data: bytes):
        return cbor2.loads(data)


@dataclass
class HashKey:
    hash: int

    @classmethod
    def from_data(cls, data: bytes):
        # data is cbor uint
        # print(f"{data=}")
        return cls(hash=cbor2.loads(data))

    @staticmethod
    def decode_value(data: bytes):
        return cbor2.loads(data)


@dataclass
class TagHashKey:
    hash: int

    @classmethod
    def from_data(cls, data: bytes):
        # print(f"key {data=}")
        return cls(hash=decode_cbor_uint(data))

    @staticmethod
    def decode_value(data: bytes):
        # print(f"value {data=}")
        return data.decode("utf-8")


@dataclass
class IndexKey:
    header: list[int]
    item: bytes | None = None
    track_id: int | None = None

    @classmethod
    def from_data(cls, data: bytes):
        # This is definitely wrong, but I'm not sure what's right.
        # print(f"{data=}")
        if not data:
            raise ValueError()

        dec = decoder(data)
        header = dec.decode()
        remaining = data[dec.fp.tell() :]
        if not remaining:
            return cls(header=header)

        # print(f"{header=} {remaining=}")

        assert remaining[0:1] == FIELD_SEPEARATOR
        remaining = remaining[1:]

        bcontent, _, btrailer = remaining.rpartition(FIELD_SEPEARATOR)

        # print(f"{bcontent=} {btrailer=}")

        if btrailer:
            trailer = decode_cbor_uint(btrailer)
            return cls(header=header, item=bcontent, track_id=trailer)
        else:
            return cls(header=header, item=bcontent)

    @staticmethod
    def decode_value(data: bytes):
        # print(f"{data=}")
        return data.decode()  # Filesystem encoding


class Prefix(Enum):
    Path = b"P"
    Data = b"D"
    Hash = b"H"
    TagHash = b"T"
    Index = b"I"


structs = {
    Prefix.Path: PathKey,
    Prefix.Data: DataKey,
    Prefix.Hash: HashKey,
    Prefix.TagHash: TagHashKey,
    Prefix.Index: IndexKey,
}


def loads(val):
    prefix, _, data = val.partition(FIELD_SEPEARATOR)
    return structs[Prefix(prefix)].from_data(data)
