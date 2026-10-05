#!/usr/bin/env python3
"""Small Linux-to-legacy-iPhone music sync tool."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=True, text=True, capture_output=capture)


def devices() -> list[str]:
    result = run(["idevice_id", "-l"], capture=True)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def choose_device(requested: str | None) -> str:
    found = devices()
    if requested:
        if requested not in found:
            raise SystemExit(f"device {requested} is not connected")
        return requested
    if len(found) != 1:
        raise SystemExit(f"expected exactly one connected device, found {len(found)}; use --udid")
    return found[0]


def db_version(udid: str) -> str:
    result = run(
        ["ideviceinfo", "-u", udid, "-q", "com.apple.mobile.iTunes", "-k", "DBVersion"],
        capture=True,
    )
    return result.stdout.strip()


def importer_path() -> str:
    candidates = [
        Path(__file__).resolve().parent / "build" / "clawpod-import",
        Path.home() / ".local" / "libexec" / "clawpod" / "clawpod-import",
        Path("/usr/local/libexec/clawpod/clawpod-import"),
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise SystemExit("clawpod-import was not found; run `make && make install`")


def helper_path(name: str) -> str:
    candidates = [
        Path(__file__).resolve().parent / "build" / name,
        Path.home() / ".local" / "libexec" / "clawpod" / name,
        Path("/usr/local/libexec/clawpod") / name,
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise SystemExit(f"{name} was not found; run `make && make install`")


def parse_track(value: str) -> tuple[int, int]:
    match = re.match(r"\s*(\d+)(?:\s*/\s*(\d+))?", value or "")
    return (int(match.group(1)), int(match.group(2) or 0)) if match else (0, 0)


def manifest_from_json(index: Path, selection: Path, output: Path) -> int:
    rows = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line]
    wanted = json.loads(selection.read_text(encoding="utf-8"))

    def norm(value: str) -> str:
        return " ".join(value.casefold().split())

    chosen = []
    for item in wanted:
        matches = [
            row for row in rows
            if norm(row.get("artist", "")) == norm(item["artist"])
            and norm(row.get("title", "")) == norm(item["title"])
        ]
        if not matches:
            raise SystemExit(f"not found in index: {item['artist']} - {item['title']}")
        row = matches[0]
        if Path(row["path"]).suffix.casefold() != ".mp3":
            raise SystemExit(f"only MP3 is currently supported: {row['path']}")
        chosen.append(row)

    with output.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# ClawPod TSV v1\n")
        for row in chosen:
            track_nr, track_count = parse_track(str(row.get("track", "")))
            year_match = re.search(r"\b(19|20)\d{2}\b", str(row.get("date", "")))
            fields = [
                row["path"], row.get("title", ""), row.get("artist", ""),
                row.get("album", ""), row.get("genre", ""),
                year_match.group(0) if year_match else "0",
                str(round(float(row.get("duration", 0)) * 1000)),
                str(track_nr), str(track_count),
                str(round(float(row.get("bitrate", 0)) / 1000) or 256),
                str(int(row.get("samplerate", 0) or 44100)),
            ]
            if any("\t" in str(value) or "\n" in str(value) for value in fields):
                raise SystemExit(f"tabs/newlines are unsupported in metadata: {row['path']}")
            handle.write("\t".join(map(str, fields)) + "\n")
    return len(chosen)


def manifest_from_paths(paths: list[str], output: Path) -> int:
    try:
        from mutagen import File as MutagenFile
    except ImportError as exc:
        raise SystemExit("the `add` command requires python-mutagen") from exc

    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path.is_dir():
            files.extend(sorted(item for item in path.rglob("*") if item.suffix.casefold() == ".mp3"))
        elif path.is_file() and path.suffix.casefold() == ".mp3":
            files.append(path)
        else:
            raise SystemExit(f"not an MP3 file or directory: {path}")
    files = list(dict.fromkeys(files))
    if not files:
        raise SystemExit("no MP3 files found")

    with output.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# ClawPod TSV v1\n")
        for path in files:
            audio = MutagenFile(path, easy=True)
            if audio is None or not hasattr(audio, "info"):
                raise SystemExit(f"could not read MP3 metadata: {path}")
            tags = audio.tags or {}

            def first(name: str, fallback: str = "") -> str:
                values = tags.get(name, [])
                return str(values[0]) if values else fallback

            title = first("title", path.stem)
            artist = first("artist", "Unknown Artist")
            album = first("album", "Unknown Album")
            genre = first("genre", "")
            date = first("date", "")
            year_match = re.search(r"\b(19|20)\d{2}\b", date)
            track_nr, track_count = parse_track(first("tracknumber", ""))
            fields = [
                str(path), title, artist, album, genre,
                year_match.group(0) if year_match else "0",
                str(round(audio.info.length * 1000)), str(track_nr), str(track_count),
                str(round(audio.info.bitrate / 1000) or 256),
                str(audio.info.sample_rate or 44100),
            ]
            if any("\t" in value or "\n" in value for value in fields):
                raise SystemExit(f"tabs/newlines are unsupported in metadata: {path}")
            handle.write("\t".join(fields) + "\n")
    return len(files)


def doctor(args: argparse.Namespace) -> None:
    udid = choose_device(args.udid)
    version = db_version(udid)
    print(f"device={udid}")
    print(f"db_version={version}")
    if version != "4":
        raise SystemExit("device is not in legacy DBVersion 4 mode; see README setup")
    print("status=ready")


def sync_manifest(udid: str, manifest: Path) -> None:
    version = db_version(udid)
    if version != "4":
        raise SystemExit(f"refusing sync: DBVersion is {version!r}, expected '4'")
    if not manifest.is_file():
        raise SystemExit(f"manifest does not exist: {manifest}")

    mount_dir = Path(tempfile.mkdtemp(prefix="clawpod-"))
    mounted = False
    try:
        run(["ifuse", "-u", udid, str(mount_dir)])
        mounted = True
        sysinfo = mount_dir / "iTunes_Control" / "Device" / "SysInfoExtended"
        hashinfo = mount_dir / "iTunes_Control" / "Device" / "HashInfo"
        library = mount_dir / "iTunes_Control" / "iTunes" / "iTunes Library.itlp" / "Library.itdb"
        if not sysinfo.is_file() or not hashinfo.is_file() or hashinfo.stat().st_size != 54:
            raise SystemExit("device bootstrap is incomplete (SysInfoExtended/HashInfo)")
        if not library.is_file():
            raise SystemExit("legacy Library.itdb is missing; see README setup")
        run([importer_path(), str(mount_dir), str(manifest)])
    finally:
        if mounted:
            subprocess.run(["fusermount", "-u", str(mount_dir)], check=False)
        shutil.rmtree(mount_dir, ignore_errors=True)


def sync(args: argparse.Namespace) -> None:
    sync_manifest(choose_device(args.udid), Path(args.manifest).resolve())


def add(args: argparse.Namespace) -> None:
    udid = choose_device(args.udid)
    descriptor, manifest_name = tempfile.mkstemp(prefix="clawpod-add-", suffix=".tsv")
    os.close(descriptor)
    manifest = Path(manifest_name)
    try:
        count = manifest_from_paths(args.paths, manifest)
        print(f"selected={count}")
        sync_manifest(udid, manifest)
    finally:
        manifest.unlink(missing_ok=True)


def verify(args: argparse.Namespace) -> None:
    udid = choose_device(args.udid)
    if db_version(udid) != "4":
        raise SystemExit("refusing verification: device is not in DBVersion 4 mode")
    mount_dir = Path(tempfile.mkdtemp(prefix="clawpod-verify-"))
    mounted = False
    try:
        run(["ifuse", "-u", udid, str(mount_dir)])
        mounted = True
        run([helper_path("clawpod-verify"), str(mount_dir)])
    finally:
        if mounted:
            subprocess.run(["fusermount", "-u", str(mount_dir)], check=False)
        shutil.rmtree(mount_dir, ignore_errors=True)


def make_manifest(args: argparse.Namespace) -> None:
    count = manifest_from_json(Path(args.index), Path(args.selection), Path(args.output))
    print(f"wrote={args.output} tracks={count}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="clawpod")
    root.add_argument("--udid", help="target a particular connected device")
    commands = root.add_subparsers(dest="command", required=True)
    check = commands.add_parser("doctor", help="check connection and legacy database mode")
    check.set_defaults(func=doctor)
    sync_cmd = commands.add_parser("sync", help="import an 11-column TSV manifest")
    sync_cmd.add_argument("manifest")
    sync_cmd.set_defaults(func=sync)
    add_cmd = commands.add_parser("add", help="import MP3 files or directories")
    add_cmd.add_argument("paths", nargs="+")
    add_cmd.set_defaults(func=add)
    verify_cmd = commands.add_parser("verify", help="check database counts and every media file")
    verify_cmd.set_defaults(func=verify)
    manifest = commands.add_parser("make-manifest", help="select tracks from a JSONL metadata index")
    manifest.add_argument("--index", required=True)
    manifest.add_argument("--selection", required=True)
    manifest.add_argument("--output", required=True)
    manifest.set_defaults(func=make_manifest)
    return root


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
