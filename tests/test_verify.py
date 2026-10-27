import base64

import cv2
import numpy as np
import pytest
from pydantic import ValidationError

from backend.verify.crops import candidate_crop, context_thumbnail, verifier_images
from backend.verify.schema import Grade, consistency_flags, grade_json_schema
from backend.verify.verifier import _extract_json

GOOD = {"is_defect": True, "defect_type": "corrosion", "severity": 3, "confidence": 0.8,
        "evidence": {"visual_cues": ["orange flaking scale"], "location": "pipe support", "extent": "small patch",
                     "mask_fit": "good"},
        "recommended_action": "clean_and_recoat"}


def test_grade_validates_and_rejects_bad_values():
    assert Grade.model_validate(GOOD).severity == 3
    for bad in ({**GOOD, "severity": 6}, {**GOOD, "confidence": 1.5}, {**GOOD, "defect_type": "mould"},
                {**GOOD, "extra": 1}):
        with pytest.raises(ValidationError):
            Grade.model_validate(bad)


def test_schema_is_strict_compatible():
    s = grade_json_schema()

    def check(obj):
        if obj.get("type") == "object":
            assert obj["additionalProperties"] is False
            assert set(obj["required"]) == set(obj["properties"])
            for v in obj["properties"].values():
                check(v)
    check(s)
    assert set(s["properties"]) == set(Grade.model_fields)


def test_consistency_flags():
    assert consistency_flags(Grade.model_validate(GOOD)) == []
    g = Grade.model_validate({**GOOD, "severity": 5, "confidence": 0.3, "recommended_action": "monitor"})
    assert {"severity_5_low_confidence", "severe_but_no_action"} <= set(consistency_flags(g))
    r = Grade.model_validate({**GOOD, "is_defect": False, "severity": 4})
    assert {"rejected_but_typed", "rejected_but_severe"} <= set(consistency_flags(r))


def test_extract_json_handles_fences_and_prose():
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json('Here: {"a": {"b": 2}} done') == '{"a": {"b": 2}}'


def test_crop_outline_and_thumbnail():
    img = np.full((640, 640, 3), 120, np.uint8)
    mask = np.zeros((640, 640), bool)
    mask[300:340, 200:260] = True
    crop = candidate_crop(img, mask, (200, 300, 260, 340))
    assert max(crop.shape[:2]) == 448
    assert ((crop == (255, 255, 0)).all(axis=2)).sum() > 100  # cyan outline drawn
    thumb = context_thumbnail(img, (200, 300, 260, 340))
    assert max(thumb.shape[:2]) == 256
    a, b = verifier_images(img, mask, (200, 300, 260, 340))
    assert a.startswith("data:image/png;base64,")
    decoded = cv2.imdecode(np.frombuffer(base64.b64decode(a.split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape == crop.shape
