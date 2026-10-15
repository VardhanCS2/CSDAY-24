import re
import unicodedata
from collections.abc import Mapping


def normalize_catalogue_search_text(
    text: str,
    aliases: Mapping[str, str] | None = None,
) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", normalized)
    normalized = " ".join(re.findall(r"[a-z]+|\d+", normalized))

    if aliases:
        normalized_aliases = [
            (
                " ".join(re.findall(r"[a-z]+|\d+", unicodedata.normalize("NFKC", alias).casefold())),
                " ".join(re.findall(r"[a-z]+|\d+", unicodedata.normalize("NFKC", target).casefold())),
            )
            for alias, target in aliases.items()
        ]
        for alias, target in sorted(normalized_aliases, key=lambda pair: len(pair[0]), reverse=True):
            if alias and target:
                normalized = re.sub(
                    rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])",
                    target,
                    normalized,
                )
    return " ".join(normalized.split())
