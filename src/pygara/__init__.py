import collections.abc
from dataclasses import dataclass
import datetime
from enum import Enum, IntEnum
import io
import typing

import plyvel
import cbor2


FIELD_SEPEARATOR = b"\0"


def _decoder(data: bytes):
    return cbor2.CBORDecoder(io.BytesIO(data))


def decode_cbor_uint(data: bytes) -> int:
    return _decoder(data).decode()


class Key[V](typing.Protocol):
    @classmethod
    def from_data(cls, data: bytes) -> typing.Self: ...

    def decode_value(self, data: bytes) -> V: ...

    def __bytes__(self) -> bytes: ...


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

    def __bytes__(self):
        return bytes(Prefix.TagHash) + FIELD_SEPEARATOR + cbor2.dumps(self.hash)

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

        dec = _decoder(data)
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

    def __bytes__(self):
        return self.value


structs = {
    Prefix.Path: PathKey,
    Prefix.Data: DataKey,
    Prefix.Hash: HashKey,
    Prefix.TagHash: TagHashKey,
    Prefix.Index: IndexKey,
}


def load_key(val):
    prefix, _, data = val.partition(FIELD_SEPEARATOR)
    return structs[Prefix(prefix)].from_data(data)


class TDict(collections.abc.Mapping):
    """
    Low-level access to the LevelDB.

    Just handles serialization, nothing about the structure of data.
    """

    _db: plyvel.DB

    SPECIAL_KEYS = (b"schema_version", b"collator")

    def __init__(self, db: plyvel.DB | plyvel._plyvel.Snapshot):
        self._db = db

    def __repr__(self):
        if isinstance(self._db, plyvel._plyvel.Snapshot):
            dbstr = "snapshot@..."
        elif isinstance(self._db, plyvel.DB):
            dbstr = f"db@{self._db.name!r}"
        else:
            dbstr = repr(self._db)
        return f"<{type(self).__name__} {dbstr}>"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._db.close()

    def close(self):
        self._db.close()

    @property
    def schema_version(self):
        return self._db.get(b"schema_version")

    @property
    def collator(self):
        return self._db.get(b"collator")

    def __getitem__(self, key: Key):
        bkey = bytes(key)
        bvalue = self._db.get(bkey)
        return key.decode_value(bvalue)

    def __iter__(self):
        for key, _ in self.items():
            yield key

    def __len__(self):
        raise NotImplementedError("Why do you need this?")

    def _iterator(self, **kwargs):
        for bkey, bvalue in self._db.iterator(**kwargs):
            if bkey in self.SPECIAL_KEYS:
                continue
            key = load_key(bkey)
            value = key.decode_value(bvalue)
            yield key, value

    def items(self) -> typing.Iterator[tuple[Key, typing.Any]]:
        yield from self._iterator()

    def snapshot(self) -> typing.Self:
        return type(self)(self._db.snapshot())

    def items_by_prefix(
        self,
        prefix: Prefix | bytes,
    ) -> typing.Iterator[tuple[Key, typing.Any]]:
        if isinstance(prefix, Prefix):
            start = bytes(prefix) + FIELD_SEPEARATOR
        else:
            start = prefix
        assert start[-1] != 0xFF
        stop = start[:-1] + bytes([start[-1] + 1])
        yield from self._iterator(
            start=start, include_start=True, stop=stop, include_stop=False
        )


TrackId = int


class Container(IntEnum):
    Unsupported = 0
    Mp3 = 1
    Wav = 2
    Ogg = 3
    Flac = 4
    Opus = 5


class MediaType(IntEnum):
    Unknown = 0
    Music = 1
    Podcast = 2
    Audiobook = 3


class Tag(IntEnum):
    Title = 0
    Artist = 1
    Album = 2
    AlbumArtist = 3
    Disc = 4
    Track = 5
    AlbumOrder = 6
    Genres = 7
    AllArtists = 8


@dataclass
class TrackData:
    _db: TDict

    id: TrackId
    filepath: str
    tags_hash: int
    is_tombstoned: bool
    modified_at_date: int
    modified_at_time: int
    individual_tag_hashes: dict[Tag, int]
    last_position: int
    track_type: MediaType
    play_count: int

    def __repr__(self):
        try:
            mtime = repr(self.modified_at)
        except Exception as e:
            mtime = f"<{type(e).__name__}>"
        return f"<{type(self).__name__} id={self.id!r} filepath={self.filepath!r} is_tombstoned={self.is_tombstoned!r} modified_at={mtime} last_position={self.last_position!r} track_type={MediaType(self.track_type)!r} play_count={self.play_count!r}>"

    def metadata(self) -> dict[Tag, str]:
        return {
            Tag(tag): self._db[TagHashKey(thash)]
            for tag, thash in self.individual_tag_hashes.items()
        }

    @property
    def modified_at(self) -> datetime.datetime | None:
        if self.modified_at_date == 0 and self.modified_at_time == 0:
            return None
        # According to Wikipedia:
        # Date bits: 0bYYYYYYYM_MMMDDDDD
        # 0-4: day (1-31)
        # 5-8: month (1-12)
        # 9-15: year (0=1980)
        # Time bits: 0bHHHHHMMM_MMMSSSSS
        # 0-4: seconds/2 (0-29, ie two second resolution)
        # 5-10: minutes (0-59)
        # 11-15: hours (0-23)
        # This aligns with http://elm-chan.org/fsw/ff/doc/sfileinfo.html
        d = (self.modified_at_date & 0b00000000_00011111)  # Day: bits 0-4
        m = (self.modified_at_date & 0b00000001_11100000) >> 5  # Month: bits 5-8
        y = (self.modified_at_date >> 9) + 1980  # Year: bits 9-15, offset from 1980

        s = (self.modified_at_time & 0b00000000_00011111) * 2  # Seconds/2: bits 0-4
        n = (self.modified_at_time & 0b00000111_11100000) >> 5  # Minutes: bits 5-10
        h = (self.modified_at_time >> 11)  # Hours: bits 11-15

    return datetime.datetime(y, m, d, h, n, s)


class TangaraDB:
    def __init__(self, path: str):
        self._db = TDict(plyvel.DB(path))

    def get_track(self, track_id: TrackId | str) -> TrackData:
        db = self._db.snapshot()
        if isinstance(track_id, str):
            # path
            track_id: TrackId = db._db[PathKey(track_id)]

        raw_data = db._db.get(DataKey(track_id))
        return TrackData(db, *raw_data)

    def iter_tracks(self) -> typing.Iterable[TrackData]:
        db = self._db.snapshot()
        for _, raw_data in db.items_by_prefix(Prefix.Data):
            yield TrackData(db, *raw_data)

    # TODO: Iter tag values
    # TODO: iter tracks by tag
