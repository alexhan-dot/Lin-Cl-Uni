"""Conservative, offline mapping for one Lineage Classic listing item.

An observed marketplace name is not proof of an NC official item name. The
catalog keeps that distinction explicit and never returns seller listing text.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import unicodedata
from typing import Any


_CATALOG = json.loads(Path(__file__).with_name("item_catalog.json").read_text(encoding="utf-8"))
MAPPING_VERSION = _CATALOG["mappingVersion"]
CATALOG_VERSION = MAPPING_VERSION
_ENTRIES = {entry["id"]: entry for entry in _CATALOG["entries"]}
_BUNDLE_WORDS = re.compile(r"일괄|묶음|세트|셋트|각종|여러|다수|쌍|택\s*\d|선택|또는|\s및\s|\d+\s*종")
_QUANTITY_WORDS = re.compile(r"(?<!\d)(\d+)\s*(?:개|자루|벌|켤레|장(?=$|[\s,.!?]|팜|판매|팝니다|급처))")
_NON_ITEM_OFFER = re.compile(r"계정|캐릭터|캐릭|육성|대리|대여|인형|삽니다|구매|매입|교환|구함|리니지\s*[mw2]|리마스터")
_RIGHT_SUFFIX = re.compile(r"^(?:판매|팝니다|팔아요|급처|급매|최저가|정리|팔아|팔고)")
_HANGUL_OR_LATIN = re.compile(r"[가-힣a-z]")
# These are observed expressions whose complete Classic item names have not
# been verified. They can exclude a mixed offer without inventing a canonical
# mapping or publishing an unsupported name.
_EXCLUSION_ONLY_ITEMS = re.compile(
    r"요방|싸울|요사|마투|보망|강장|마망|메르|마력서|벨트달린가죽조끼|"
    r"완반|완력의반지|젤|데이|수룡|화룡|청명|티셔츠|"
    r"방패|지팡이|망토|투구|갑옷|반지|목걸이|벨트|주문서|물약|아데나|"
    r"정령의수정|기술서|마법서"
)
_SHORT_EXCLUSION_ITEM = re.compile(r"(?<![가-힣a-z])(?:\+?\d{1,2})?티(?![가-힣a-z])")


def normalize_title(title: str) -> str:
    """Normalize equivalent Unicode and spacing without publishing the title."""
    if not isinstance(title, str):
        return ""
    title = unicodedata.normalize("NFKC", unicodedata.normalize("NFC", title)).casefold()
    title = title.replace("\u200b", "").replace("\ufeff", "")
    return re.sub(r"\s+", " ", title).strip()


def get_item(item_id: str) -> dict[str, Any] | None:
    """Return registered metadata; officialVerified states its evidence level."""
    entry = _ENTRIES.get(item_id) if isinstance(item_id, str) else None
    return copy.deepcopy(entry) if entry else None


def public_catalog() -> dict[str, Any]:
    entries = []
    for entry in _CATALOG["entries"]:
        entries.append({
            "id": entry["id"],
            "name": entry["name"],
            "aliases": [alias["value"] for alias in entry["aliases"]],
            "category": entry["category"],
            "referenceUrl": entry["referenceUrl"],
            "officialVerified": entry["officialVerified"],
            "verification": entry["verification"],
            "enhanceable": entry["enhanceable"],
            "officialSource": copy.deepcopy(entry.get("officialSource")),
            **({"inherentBlessing": entry["inherentBlessing"]}
               if entry.get("inherentBlessing") is not None else {}),
        })
    return {
        "version": MAPPING_VERSION,
        "mappingVersion": MAPPING_VERSION,
        "game": copy.deepcopy(_CATALOG["game"]),
        "verifiedAt": _CATALOG["verifiedAt"],
        "verificationScope": _CATALOG["verificationScope"],
        "officialVerifiedCount": sum(entry["officialVerified"] for entry in entries),
        "sources": copy.deepcopy(_CATALOG["sources"]),
        "entries": entries,
    }


def _alias_pattern(value: str) -> re.Pattern[str]:
    # Sellers commonly remove canonical-name spaces. Longest matching below
    # prevents short aliases from overriding a complete name.
    compact = re.sub(r"\s+", "", normalize_title(value))
    return re.compile(r"\s*".join(re.escape(char) for char in compact))


_ALIASES = sorted(
    [(entry["id"], value, _alias_pattern(value))
     for entry in _CATALOG["entries"]
     for value in dict.fromkeys([entry["name"], *(a["value"] for a in entry["aliases"])])],
    key=lambda row: len(re.sub(r"\s+", "", row[1])), reverse=True,
)


def _valid_boundary(text: str, start: int, end: int) -> bool:
    if start and _HANGUL_OR_LATIN.fullmatch(text[start - 1]):
        prefix = text[:start]
        if not re.search(r"(?:축복받은|저주받은|축복|축|저주|일반|비축|미확인)\s*$", prefix):
            return False
    return not (end < len(text) and _HANGUL_OR_LATIN.fullmatch(text[end])
                and not _RIGHT_SUFFIX.match(text[end:]))


def _find_items(text: str) -> list[tuple[str, int, int]]:
    found: list[tuple[str, int, int]] = []
    for item_id, _, pattern in _ALIASES:
        for match in pattern.finditer(text):
            if not _valid_boundary(text, match.start(), match.end()):
                continue
            if any(match.start() >= start and match.end() <= end for _, start, end in found):
                continue
            found.append((item_id, match.start(), match.end()))
    return sorted(found, key=lambda row: row[1])


def _has_additional_unmapped_item(text: str, found: list[tuple[str, int, int]]) -> bool:
    masked = list(text)
    for _, start, end in found:
        masked[start:end] = " " * (end - start)
    remaining = "".join(masked)
    compact = re.sub(r"\s+", "", remaining)
    return bool(_EXCLUSION_ONLY_ITEMS.search(compact) or _SHORT_EXCLUSION_ITEM.search(remaining)
                # An item connected with 과/와 can fail the normal boundary
                # check. Retain it as exclusion evidence rather than dropping
                # it and accepting only the last item of a bundle.
                or any(pattern.search(remaining) for _, _, pattern in _ALIASES))


def _blessing(text: str, start: int, single_item: bool = False) -> str | None:
    states = set()
    prefix = re.sub(r"[\[\](){}]", " ", text[:start])
    positive_text = re.sub(r"비\s*축복", "", text)
    if ("축복" in positive_text
            or re.search(r"(?:^|\s)축\s*(?:\+?\s*\d{1,2}\s*)?$", prefix)
            or (single_item and re.search(r"[\[({]\s*축\s*[\])}]", text))):
        states.add("blessed")
    if "저주" in text:
        states.add("cursed")
    if re.search(r"일반|비축|비\s*축복", text):
        states.add("normal")
    return next(iter(states)) if len(states) == 1 else "unknown" if not states else None


def _enchant(text: str, start: int, end: int) -> tuple[int | None, bool]:
    values = []
    prefix = text[:start]
    suffix = text[end:]
    before = re.search(r"(?<![\d,])(?:\+\s*)?(\d{1,2})\s*(?:강화|강)?\s*$", prefix)
    after = re.match(r"\s*(?:\+\s*(\d{1,2})(?!\d)|(?:\s+)(\d{1,2})\s*(?:강화|강))", suffix)
    if before:
        values.append(int(before.group(1)))
    if after:
        values.append(int(after.group(1) or after.group(2)))
    if len(set(values)) > 1 or any(value < 0 or value > 15 for value in values):
        return None, False
    if re.search(r"\d\s*[~〜∼]\s*\+?\d|\d\s*[-–]\s*\+?\d", text):
        return None, False
    return values[0] if values else None, True


def classify_title(title: str, quantity: int | None = None) -> dict[str, Any]:
    """Explain a safe match using enums; never return private listing content."""
    text = normalize_title(title)
    if not text or len(text) > 1000:
        return {"status": "invalid", "reason": "invalid_title", "match": None}
    if quantity is not None and (isinstance(quantity, bool) or not isinstance(quantity, int)
                                 or not 1 <= quantity <= 1_000_000):
        return {"status": "invalid", "reason": "invalid_quantity", "match": None}
    found = _find_items(text)
    if not found:
        return {"status": "unmapped", "reason": "unknown_item", "match": None}
    if _has_additional_unmapped_item(text, found):
        return {"status": "ambiguous", "reason": "additional_unmapped_item", "match": None}
    if _NON_ITEM_OFFER.search(text):
        return {"status": "ambiguous", "reason": "non_item_offer", "match": None}
    # Identification affects value but is not a current aggregation dimension.
    # Keep those rows excluded until that dimension is explicitly supported.
    if "미확인" in text:
        return {"status": "ambiguous", "reason": "unidentified_item", "match": None}
    if _BUNDLE_WORDS.search(text):
        return {"status": "ambiguous", "reason": "bundle_offer", "match": None}
    title_quantities = [int(match.group(1)) for match in _QUANTITY_WORDS.finditer(text)]
    if title_quantities and (len(set(title_quantities)) != 1
                             or any(count < 1 for count in title_quantities)
                             or (title_quantities[0] > 1 and quantity != title_quantities[0])):
        return {"status": "ambiguous", "reason": "unconfirmed_quantity", "match": None}
    # A seller can repeat a full name and its alias for one item. Explicit
    # source quantity disambiguates that repetition; attributes still must
    # agree below, and an explicit title quantity must agree above.
    if len({row[0] for row in found}) != 1 or (len(found) > 1 and quantity is None):
        return {"status": "ambiguous", "reason": "multiple_items", "match": None}
    separator = re.compile(r"[/／|｜&＆,，;；]|(?<=[가-힣a-z0-9])\s*\+\s*(?=[가-힣a-z])")
    if separator.search(text):
        parts = [part.strip() for part in separator.split(text) if part.strip()]
        if len(found) < 2 or any(not _find_items(part) for part in parts):
            return {"status": "ambiguous", "reason": "bundle_offer", "match": None}
    item_id, start, end = found[0]
    entry = _ENTRIES[item_id]
    enchantments = [_enchant(text, start, end) for _, start, end in found]
    enchant, _ = enchantments[0]
    if (any(not valid for _, valid in enchantments)
            or len({value for value, _ in enchantments}) != 1
            or (enchant is not None and not entry["enhanceable"])):
        return {"status": "ambiguous", "reason": "invalid_enchant", "match": None}
    blessings = [_blessing(text, start, single_item=len(found) == 1) for _, start, _ in found]
    known_blessings = {value for value in blessings if value != "unknown"}
    if None in blessings or len(known_blessings) > 1:
        return {"status": "ambiguous", "reason": "conflicting_blessing", "match": None}
    if quantity is not None and quantity > 1 and len(set(blessings)) > 1:
        return {"status": "ambiguous", "reason": "unconfirmed_blessing", "match": None}
    # When one item is described by both a full name and an alias, its one
    # explicit blessing can apply to that single source-confirmed item.
    blessing = next(iter(known_blessings)) if known_blessings else "unknown"
    inherent_blessing = entry.get("inherentBlessing")
    if inherent_blessing is not None:
        if blessing not in ("unknown", inherent_blessing):
            return {"status": "ambiguous", "reason": "conflicting_blessing", "match": None}
        blessing = inherent_blessing
    return {"status": "mapped", "reason": "single_item", "match": {
        "itemId": item_id,
        "itemName": entry["name"],
        "enchant": enchant,
        "blessing": blessing,
        "mappingVersion": MAPPING_VERSION,
    }}


def match_item(title: str, quantity: int | None = None) -> dict[str, Any] | None:
    return classify_title(title, quantity=quantity)["match"]


def mapping_status(title: str, quantity: int | None = None) -> str:
    return classify_title(title, quantity=quantity)["status"]
