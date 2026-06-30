// Copyright: Ankitects Pty Ltd and contributors
// License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

use std::env;
use std::sync::LazyLock;

pub fn version() -> &'static str {
    include_str!("../../.version").trim()
}

/// Build flavor for this fork. Surfaced in the desktop About screen so it is
/// obvious at a glance that the running binary is the Speedrun engine rather
/// than upstream Anki. Kept separate from `version()` so the sync handshake
/// string is unaffected.
pub fn build_flavor() -> &'static str {
    "Speedrun"
}

pub fn buildhash() -> &'static str {
    option_env!("BUILDHASH").unwrap_or("dev").trim()
}

pub(crate) fn sync_client_version() -> &'static str {
    static VER: LazyLock<String> = LazyLock::new(|| {
        format!(
            "anki,{version} ({buildhash}),{platform}",
            version = version(),
            buildhash = buildhash(),
            platform = env::var("PLATFORM").unwrap_or_else(|_| env::consts::OS.to_string())
        )
    });
    &VER
}

pub(crate) fn sync_client_version_short() -> &'static str {
    static VER: LazyLock<String> = LazyLock::new(|| {
        format!(
            "{version},{buildhash},{platform}",
            version = version(),
            buildhash = buildhash(),
            platform = env::consts::OS
        )
    });
    &VER
}

#[cfg(test)]
mod test {
    use super::*;

    #[test]
    fn speedrun_build_flavor() {
        assert_eq!(build_flavor(), "Speedrun");
    }

    #[test]
    fn version_is_not_empty() {
        assert!(!version().is_empty());
    }
}
