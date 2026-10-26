"""개발용 AI Mock (키워드 분류)

- 코드: 실제 DB survey_items 52항목만 사용 (tests/integration에서 검증)
- 키워드 여러 개 일치 → 여러 항목
- 일치 없음 → 미분류 (빈 결과)
- 테스트용 표식
  - [ai-fail]    → 예외 (실패·재시도 흐름)
  - [ai-low]     → 기준 미만 확신도 (걸러짐 → 미분류)
  - [ai-invalid] → 52항목에 없는 코드 (걸러짐)
"""
from app.ai.interfaces import ItemClassification


MOCK_CONFIDENCE = 0.9

KEYWORDS: dict[str, tuple[str, ...]] = {
    "phys_dressing": ("옷 입", "옷을 입", "옷 갈아"),
    "phys_wash_face": ("세수",),
    "phys_brush_teeth": ("양치",),
    "phys_bathing": ("목욕", "샤워"),
    "phys_eating": ("식사", "밥", "반찬", "드셨"),
    "phys_transfer": ("옮겨 앉", "휠체어"),
    "phys_toilet_use": ("화장실",),
    "phys_bowel_control": ("대변", "변비"),
    "phys_bladder_control": ("소변", "오줌"),
    "cog_short_memory": ("기억", "깜빡"),
    "cog_date_disorient": ("날짜", "요일"),
    "cog_place_disorient": ("어딘지", "어디인지"),
    "beh_hallucination": ("환청", "환각"),
    "beh_sad_crying": ("우셨", "울기", "울었"),
    "beh_irregular_sleep": ("못 주무", "밤에 깨", "낮밤"),
    "beh_wandering": ("길을 잃", "길 잃"),
    "beh_verbal_abuse": ("화내", "폭언", "욕을"),
    "beh_going_out": ("현관", "밖으로 나가"),
    "beh_hiding": ("숨기", "감추"),
    "nur_wound": ("욕창",),
    "reh_joint_knee": ("무릎",),
}


class MockRecordClassifier:
    def classify(self, text: str) -> list[ItemClassification]:
        if "[ai-fail]" in text:
            raise RuntimeError("Mock AI 오류 ([ai-fail])")

        if "[ai-low]" in text:
            return [ItemClassification(item_code="phys_eating", confidence=0.3)]

        if "[ai-invalid]" in text:
            return [ItemClassification(item_code="not_a_survey_code", confidence=0.9)]

        return [
            ItemClassification(item_code=code, confidence=MOCK_CONFIDENCE)
            for code, words in KEYWORDS.items()
            if any(word in text for word in words)
        ]
