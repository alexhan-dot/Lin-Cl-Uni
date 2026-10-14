import copy
import unicodedata
import unittest

from market.item_catalog import (
    MAPPING_VERSION, classify_title, get_item, match_item, normalize_title,
    public_catalog,
)


class ItemCatalogTests(unittest.TestCase):
    def test_unicode_spaces_and_observed_aliases_map_to_same_item(self):
        for title in ["8화검", "+8 화염의 검", "８화염의검", "8 화 염 의 검",
                      unicodedata.normalize("NFD", "8화염의 검"), "8\u200b화검"]:
            with self.subTest(title=title):
                result = match_item(title)
                self.assertEqual(result["itemId"], "lc-fire-sword")
                self.assertEqual(result["enchant"], 8)
                self.assertEqual(result["mappingVersion"], MAPPING_VERSION)

    def test_enchantment_placement_and_unknown_are_preserved(self):
        for title in ["7강부", "강철 부츠 +7", "강철 부츠 7강"]:
            self.assertEqual(match_item(title)["enchant"], 7)
        self.assertIsNone(match_item("화검")["enchant"])
        self.assertEqual(match_item("화검")["blessing"], "unknown")
        self.assertEqual(match_item("0화검")["enchant"], 0)

    def test_explicit_blessing_dimensions_do_not_merge(self):
        cases = {"축7화검": "blessed", "축복받은 7화검": "blessed",
                 "저주 7화검": "cursed", "일반 7화검": "normal",
                 "비축복 7화검": "normal", "7화검": "unknown",
                 "[축]7화검": "blessed", "(축) 화검": "blessed",
                 "축 7화검": "blessed", "7화검 [축]": "blessed",
                 "[저주] 화염의 검": "cursed"}
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(match_item(title)["blessing"], expected)
        self.assertIsNone(match_item("축복 저주 7화검"))
        self.assertIsNone(match_item("일반 축복 7화검"))
        self.assertIsNone(match_item("축복7화검 비축복7화염의검", quantity=2))

    def test_substrings_wrong_game_and_non_item_offers_are_excluded(self):
        for title in ["화염의검사", "초화검", "리니지M 8화검", "리니지W 화검",
                      "화검 대여", "화검 포함 계정", "화검 인형", "화검 삽니다"]:
            with self.subTest(title=title):
                self.assertIsNone(match_item(title))
        self.assertEqual(match_item("8화검판매합니다")["itemId"], "lc-fire-sword")

    def test_multiple_items_and_uncertain_identification_are_excluded(self):
        for title in ["7강부+6수중부츠", "7화검 8화검", "7화검/7화염의검",
                      "화검 및 화활", "화검 2개", "화검 일괄", "화검 세트",
                      "미확인변반", "미확인 변신조종반지"]:
            with self.subTest(title=title):
                self.assertIsNone(match_item(title))
                self.assertEqual(classify_title(title)["status"], "ambiguous")

    def test_conflicting_or_impossible_enchantment_is_not_inferred(self):
        for title in ["16화검", "7화검 +8", "7~9화검", "7-9화검", "7변반",
                      "+7 트리플애로우"]:
            with self.subTest(title=title):
                self.assertIsNone(match_item(title))
        self.assertEqual(match_item("변신조종반지")["itemId"], "lc-polymorph-control-ring")

    def test_identical_items_require_confirmed_source_quantity(self):
        self.assertEqual(match_item("8화검 2개", quantity=2)["enchant"], 8)
        self.assertEqual(match_item("8화검8화염의검", quantity=2)["enchant"], 8)
        self.assertEqual(match_item("8화검8화염의검 팜", quantity=1)["enchant"], 8)
        self.assertEqual(match_item("8화검/8화염의검", quantity=2)["enchant"], 8)
        for title, quantity in [("8화검 2개", 1), ("8화검 2개", 3),
                                ("8화검9화염의검", 2), ("화검/화검/다른무기", 2),
                                ("화검/화활", 2), ("화검+다른상품", 2), ("8화검 2종", 2)]:
            with self.subTest(title=title, quantity=quantity):
                self.assertIsNone(match_item(title, quantity=quantity))
        for quantity in [True, 0, -1, 1.5, "2"]:
            self.assertEqual(classify_title("화검", quantity=quantity)["status"], "invalid")

    def test_unmapped_observed_items_do_not_hide_in_a_known_item_offer(self):
        for title in ["7화검 6요방", "화염의검 싸울", "화검 축젤 2장",
                      "7화검과6요방", "화검7티", "화검 메르키오르벨트",
                      "화검 물약 2개", "화검 완반"]:
            with self.subTest(title=title):
                self.assertIsNone(match_item(title, quantity=2))
        self.assertEqual(match_item("5풍룡비늘갑옷")["itemId"], "lc-wind-dragon-armor")
        self.assertIsNone(match_item("메르키오르벨트"))
        self.assertIsNone(match_item("4메르"))
        self.assertEqual(match_item("4메르모")["itemId"], "lc-melchior-cap")

    def test_compact_blessings_in_repeated_names_stay_separate(self):
        self.assertIsNone(match_item("일반7화검 축7화염의검", quantity=2))
        self.assertIsNone(match_item("7화검 축7화염의검", quantity=2))
        self.assertEqual(match_item("7화검 축7화염의검", quantity=1)["blessing"], "blessed")

    def test_verified_complete_item_names_and_prior_seller_names(self):
        cases = {"7용기부츠": ("lc-courage-boots", "용기의 부츠"),
                 "7마나지팡이": ("lc-mana-staff", "마나의 지팡이"),
                 "오우거벨트": ("lc-ogre-belt", "오우거의 벨트"),
                 "트리플애로우": ("lc-triple-arrow", "정령의 수정(트리플 애로우)"),
                 "쇼크스턴": ("lc-shock-stun", "기술서 (쇼크 스턴)"),
                 "7요방": ("lc-elven-shield", "요정족 방패"),
                 "7보망": ("lc-protection-cloak", "보호 망토"),
                 "정령의 수정(트리플 애로우)": ("lc-triple-arrow", "정령의 수정(트리플 애로우)")}
        for title, (item_id, canonical_name) in cases.items():
            with self.subTest(title=title):
                result = match_item(title)
                self.assertEqual((result["itemId"], result["itemName"]), (item_id, canonical_name))
                self.assertTrue(get_item(item_id)["officialVerified"])
        self.assertEqual(match_item("축복 받은 갑옷 마법 주문서")["blessing"], "blessed")
        self.assertIsNone(match_item("기술서(트리플애로우)"))

    def test_newly_observed_aliases_use_verified_names_and_fixed_blessing(self):
        sword = match_item("7싸울")
        self.assertEqual(sword["itemName"], "싸울아비 장검")
        self.assertEqual(sword["enchant"], 7)
        scroll = match_item("축데이")
        self.assertEqual(scroll["itemName"], "축복 받은 무기 마법 주문서")
        self.assertEqual(scroll["blessing"], "blessed")
        for title in ["일반 축데이", "저주 축데이", "7화검 싸울", "7화검과6싸울"]:
            self.assertIsNone(match_item(title, quantity=2))
        self.assertEqual(match_item("축데이 2장", quantity=2)["blessing"], "blessed")
        self.assertIsNone(match_item("축데이 2장", quantity=1))
        self.assertIsNone(match_item("축데이 2장"))
        self.assertIsNone(match_item("젤"))
        self.assertIsNone(match_item("데이"))

    def test_only_whitelisted_metadata_is_returned(self):
        result = match_item("7화검 연락은 판매자에게")
        self.assertEqual(set(result), {"itemId", "itemName", "enchant", "blessing", "mappingVersion"})
        self.assertNotIn("연락", str(result))
        self.assertEqual(classify_title(None)["status"], "invalid")
        self.assertEqual(classify_title("미등록 상품")["status"], "unmapped")

    def test_catalog_evidence_and_copies_keep_pending_names_distinct(self):
        catalog = public_catalog()
        self.assertEqual(catalog["game"]["id"], "lineage-classic")
        self.assertTrue(catalog["entries"])
        for entry in catalog["entries"]:
            if entry["officialVerified"]:
                self.assertIsInstance(entry["officialSource"], dict)
                self.assertTrue(entry["officialSource"]["url"].startswith("https://lineageclassic.plaync.com/"))
                self.assertEqual(entry["officialSource"]["serviceId"], 57)
                self.assertIsInstance(entry["officialSource"]["guideId"], int)
                name = normalize_title(entry["name"]).replace(" ", "")
                quote = normalize_title(entry["officialSource"]["quote"]).replace(" ", "")
                self.assertIn(name, quote)
            else:
                self.assertEqual(entry["verification"], "marketplace_only")
        entry = get_item("lc-fire-sword")
        original = copy.deepcopy(entry)
        entry["name"] = "changed"
        self.assertEqual(get_item("lc-fire-sword"), original)
        self.assertIsNone(get_item("unregistered-id"))


if __name__ == "__main__":
    unittest.main()
