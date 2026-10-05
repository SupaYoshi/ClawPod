# ClawPod

ClawPod is a small Linux sync tool for putting MP3 music into the native Music
app on jailbroken legacy iPhones and iPods. It combines libimobiledevice,
ifuse and libgpod, checks the device before writing, and skips tracks already
present by artist/title. Repeated sync/test entries are removed automatically.

The initial target is an iPhone 4S using the legacy iTunes DBVersion 4 format.
This is intentionally experimental: keep a backup when the device contains
anything important.

## Dependencies

- libimobiledevice (`idevice_id`, `ideviceinfo`)
- ifuse and FUSE
- libgpod plus its development headers
- GLib plus its development headers
- a C compiler and `pkg-config`
- Python 3

On Arch Linux:

```sh
sudo pacman -S libimobiledevice ifuse libgpod glib2 pkgconf gcc
make
make install
```

## Commands

```sh
clawpod doctor
clawpod sync selection.tsv
clawpod verify
```

`sync` requires an initialized DBVersion 4 library, a 54-byte `HashInfo`, and
`SQLiteDB=true` in `iTunes_Control/Device/SysInfoExtended`. It refuses to write
when those safety checks fail.

`verify` parses the resulting iPod database, compares the master-playlist count,
and checks that every referenced media file is present.

The TSV format has eleven tab-separated fields:

```text
source title artist album genre year duration_ms track_nr track_count bitrate_kbps samplerate
```

The `make-manifest` helper can convert a JSONL metadata index plus a JSON list
of `{ "artist": ..., "title": ... }` objects into this TSV format.

## Device preparation

Apple's newer database signature is not supported by libgpod. A jailbroken
legacy device can instead be configured to expose DBVersion 4. The preparation
is device- and iOS-specific and changes `/System/Library/Lockdown/Checkpoint.xml`;
make an exact backup first. `SysInfoExtended` must also advertise DBVersion 4
and `SQLiteDB=true`, after which libgpod can initialize the library. ClawPod
does not silently perform this system-level patch.

## Privacy

ClawPod does not upload device identifiers or music metadata. The sync runs
locally over USB.

## License

MIT
