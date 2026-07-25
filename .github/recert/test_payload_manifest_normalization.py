#!/usr/bin/env python3
import gzip

from payload_manifest import normalized


def stable(path: str, data: bytes) -> tuple[str, bytes]:
    return normalized(path, data)


def main() -> None:
    description_lf = b"Package: SplitAlignerR\nPackaged: 2026-01-01 UTC; runner\nVersion: 0.1.0\n"
    description_crlf = (
        b"Package: SplitAlignerR\r\n"
        b"Packaged: 2026-02-02 UTC; runneradmin\r\n"
        b"Version: 0.1.0\r\n"
    )
    assert stable("SplitAlignerR/DESCRIPTION", description_lf) == stable(
        "SplitAlignerR/DESCRIPTION", description_crlf
    )

    vignette_r_lf = b"x <- 1\nprint(x)\n"
    vignette_r_crlf = b"x <- 1\r\nprint(x)\r\n"
    assert stable("SplitAlignerR/inst/doc/quick-start.R", vignette_r_lf) == stable(
        "SplitAlignerR/inst/doc/quick-start.R", vignette_r_crlf
    )

    html_posix = b'<html lang="">\n<body>stable</body>\n'
    html_windows = b'<html lang="eng">\r\n<body>stable</body>\r\n'
    assert stable("SplitAlignerR/inst/doc/quick-start.html", html_posix) == stable(
        "SplitAlignerR/inst/doc/quick-start.html", html_windows
    )

    compressed = bytearray(gzip.compress(b"stable serialized payload", mtime=0))
    posix_container = bytes(compressed[:9] + bytes([3]) + compressed[10:])
    windows_container = bytes(compressed[:9] + bytes([6]) + compressed[10:])
    assert stable("SplitAlignerR/build/partial.rdb", posix_container) == stable(
        "SplitAlignerR/build/partial.rdb", windows_container
    )

    classification, content = stable(
        "SplitAlignerR/build/vignette.rds", b"platform-specific metadata"
    )
    assert classification == "declared_nondeterministic_build_metadata"
    assert content == b""
    print("payload_manifest_normalization_selftest: PASS")


if __name__ == "__main__":
    main()
