# -*- coding: utf-8 -*-
"""Классификация файлов ресурсов RPG Maker и Ren'Py."""
from __future__ import annotations

import posixpath
from dataclasses import dataclass
from enum import Enum


class ResourceKind(str, Enum):
    IMAGE = "image"
    ANIMATED = "animated"
    AUDIO = "audio"
    VIDEO = "video"


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga",
              ".tif", ".tiff", ".ico", ".svg", ".svgz")
ANIMATED_EXTS = (".gif", ".apng", ".gif_")
AUDIO_EXTS = (".ogg", ".oga", ".opus", ".m4a", ".wav", ".mp3",
              ".flac", ".aac", ".wma")
VIDEO_EXTS = (".webm", ".mp4", ".m4v", ".avi", ".mov", ".ogv",
              ".mkv", ".wmv", ".3gp")
RPGM_ENC_IMAGE = (".png_", ".jpg_", ".jpeg_", ".webp_", ".gif_",
                  ".rpgmvp")
RPGM_ENC_AUDIO = (".ogg_", ".oga_", ".opus_", ".m4a_", ".mp3_",
                  ".flac_", ".aac_", ".rpgmvo")
RPGM_ENC_VIDEO = (".webm_", ".mp4_", ".m4v_", ".avi_", ".mov_",
                  ".ogv_", ".mkv_", ".wmv_", ".rpgmvm")
TAG_IMAGE = "image"
TAG_ANIMATED = "animated"
TAG_AUDIO = "audio"
TAG_VIDEO = "video"


@dataclass(frozen=True)
class ResourceEntry:
    kind: ResourceKind
    path: str
    display: str
    size: int = 0
    source: str = "view"
    archive: str = ""

    @property
    def tag(self) -> str:
        return self.kind.value

    @property
    def is_archive(self) -> bool:
        return self.source == "archive"


def _path(path: str) -> str:
    return str(path or "").replace("\\", "/").lower()


def _in_movies(path: str) -> bool:
    return any(part == "movies" for part in _path(path).split("/"))


def _plain_ext(path: str) -> str:
    low = _path(path)
    for enc, plain in (
        (".rpgmvp", ".png"), (".png_", ".png"),
        (".gif_", ".gif"), (".jpg_", ".jpg"), (".jpeg_", ".jpeg"),
        (".webp_", ".webp"), (".rpgmvo", ".ogg"), (".ogg_", ".ogg"),
        (".oga_", ".oga"), (".opus_", ".opus"), (".m4a_", ".m4a"),
        (".mp3_", ".mp3"), (".flac_", ".flac"), (".aac_", ".aac"),
        (".rpgmvm", ".webm"), (".webm_", ".webm"), (".mp4_", ".mp4"),
        (".m4v_", ".m4v"), (".avi_", ".avi"), (".mov_", ".mov"),
        (".ogv_", ".ogv"), (".mkv_", ".mkv"), (".wmv_", ".wmv"),
    ):
        if low.endswith(enc):
            return plain
    return posixpath.splitext(low)[1]


def classify(path: str, folder: str = "") -> ResourceKind | None:
    """Определяет тип ресурса; movies/ важнее неоднозначного .rpgmvm."""
    low = _path(path)
    movie_path = low if not folder else folder + "/" + low
    if low.endswith(".rpgmvm") and not _in_movies(movie_path):
        return None
    if low.endswith(RPGM_ENC_VIDEO) and _in_movies(movie_path):
        return ResourceKind.VIDEO
    if low.endswith(RPGM_ENC_IMAGE):
        return (ResourceKind.ANIMATED if low.endswith((".gif_", ".apng"))
                else ResourceKind.IMAGE)
    if low.endswith(RPGM_ENC_AUDIO):
        return ResourceKind.AUDIO
    if low.endswith(RPGM_ENC_VIDEO):
        return ResourceKind.VIDEO
    ext = _plain_ext(low)
    if ext in ANIMATED_EXTS:
        return ResourceKind.ANIMATED
    if ext in IMAGE_EXTS:
        return ResourceKind.IMAGE
    if ext in AUDIO_EXTS:
        return ResourceKind.AUDIO
    if ext in VIDEO_EXTS:
        return ResourceKind.VIDEO
    return None


def plain_extension(path: str) -> str:
    return _plain_ext(path) or ".bin"


def export_name(name: str) -> str:
    """Имя для сохранения расшифрованного ресурса с обычным расширением."""
    base = posixpath.basename(str(name or "").replace("\\", "/"))
    root, _dot, _ext = base.rpartition(".")
    if not root:
        return base + plain_extension(base)
    return root + plain_extension(base)


def is_encrypted(path: str) -> bool:
    return _path(path).endswith(RPGM_ENC_IMAGE + RPGM_ENC_AUDIO
                                + RPGM_ENC_VIDEO)
