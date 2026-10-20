# Firmware signature library

This product-owned synchronous driver uses Binwalk 3.1.0 as a normal Rust
library dependency, licensed under MIT, copyright 2024 devttys0.
Source: https://github.com/ReFirmLabs/binwalk and the exact crates.io release
pinned in Cargo.lock. Cargo retains dependency licenses in its registry sources.
The Binwalk license is also included in LICENSE-BINWALK.

The driver does not execute the upstream CLI or use its worker pool. It reads
the retained input once and publishes one Analysis JSON record after the
library's synchronous scan returns. It does not extract archives or execute
firmware. Existing native Python readers perform those product operations.

The upstream CLI's queued-worker/result race is described at
https://github.com/ReFirmLabs/binwalk/issues/971. The generic CLI remains an
explicitly selectable alternative; a missing report from it stays a gap.
