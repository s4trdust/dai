"""Ask Gemini to describe a scrap piece. Returns a dict that matches SCHEMA."""
import json

import httpx
from google.genai import errors, types

from . import config

MATERIALS = [
    "acrylic", "pla", "other_plastic", "cardboard", "paper", "wood", "mdf",
    "wire", "metal", "electronics", "fabric", "foam", "glass", "unknown",
]
# "reuse" = can be stored; anything else is rejected and the person is told where to take it
DISPOSAL = ["reuse", "battery", "e_waste", "not_accepted", "hazard"]
# how each material is written in the library (matches the website's EXPIRY_DAYS keys)
MATERIAL_LABELS = {"pla": "PLA", "mdf": "MDF", "other_plastic": "Plastic"}

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "short library name, e.g. 'Plywood offcut'"},
        "material": {"type": "string", "enum": MATERIALS},
        "material_confidence": {"type": "number", "minimum": 0, "maximum": 1,
                                "description": "how sure you are of the material"},
        "colour": {"type": "string", "enum": [
            "black", "white", "grey", "silver", "gold", "copper", "brown", "red", "orange",
            "yellow", "green", "blue", "purple", "pink", "clear", "multicoloured"]},
        "condition": {"type": "string", "enum": ["intact", "minor_damage", "major_damage", "broken_fragment"]},
        "transparency": {"type": "string", "enum": ["opaque", "translucent", "transparent"]},
        "estimated_thickness_cm": {"type": "number", "description": "rough guess; 0 if impossible to judge"},
        "suggested_use": {"type": "string", "description": "a few student project ideas, comma separated"},
        "description": {"type": "string", "description": "one or two sentences: shape, damage, notable features"},
        "length_cm": {"type": "number", "description": "the measured length if given, else your estimate"},
        "width_cm": {"type": "number", "description": "the measured width if given, else your estimate"},
        "is_component": {"type": "boolean", "description": "true for a distinct reusable object (e.g. "
                         "Arduino, motor, sensor, tool); false for raw material or offcuts"},
        "disposal": {"type": "string", "enum": DISPOSAL,
                     "description": "'reuse' if the scrapyard can store it; otherwise why it must go elsewhere"},
    },
    "required": ["name", "material", "material_confidence", "colour", "condition", "transparency",
                 "estimated_thickness_cm", "suggested_use", "description", "length_cm", "width_cm",
                 "is_component", "disposal"],
}

SYSTEM_PROMPT = """You inspect pieces of scrap deposited at a school scrapyard.

Usually the piece lies on a measuring board photographed from directly above. The \
board has a grid labelled in cm and four black-and-white square markers at its \
corners; ignore the markers and grid except as a size reference. You may get a \
second image: a straightened top-down view with the detected piece outlined in \
green (red box = measured bounding rectangle). Sometimes a student photographs the \
item by hand with a phone instead; then estimate its size from the photo (rulers, \
hands, familiar objects) and say so in the description.

Length, width, area and weight, when given, are measured by instruments - use them \
as facts, do not re-estimate them. Use them as evidence: weight divided by \
(area x your thickness estimate) gives a density, e.g. acrylic ~1.2 g/cm3, PLA ~1.25, \
cardboard ~0.1-0.7, wood ~0.4-0.8, aluminium ~2.7, steel ~7.8.

"wire" means electrical wire or cable; it is raw material (is_component false), even \
with plugs or connectors on the ends. "pla" means 3D-printed plastic (visible layer \
lines, typical printed shapes). When the evidence does not settle the material, pick \
the most likely option and lower material_confidence, or answer "unknown". An honest \
low confidence is far more useful than a confident wrong answer, because uncertain \
pieces are checked by a person. If grid lines are visible through the piece it is \
transparent or translucent.

Set disposal to "reuse" for anything the scrapyard can store for students to reuse. \
Otherwise: "battery" for batteries, power banks or devices with a built-in battery; \
"e_waste" for burnt, broken or clearly dead electronics; "not_accepted" for furniture, \
stationery, plushies, textbooks and similar everyday items; "hazard" for anything \
leaking, contaminated, sharp-edged or dangerously damaged. Working electronics and \
ordinary offcuts are "reuse"."""


class ClassificationError(Exception):
    pass


def material_label(material: str) -> str:
    return MATERIAL_LABELS.get(material, material.capitalize())


def classify(client, models: list[str], photo_jpeg: bytes, annotated_jpeg: bytes | None,
             weight_g: float | None, length_cm: float | None, width_cm: float | None,
             area_cm2: float | None, hand_photo: bool = False) -> dict:
    if client is None:
        raise ClassificationError("Gemini not configured (set GEMINI_API_KEY)")
    facts = f"Weight: {weight_g:.1f} g." if weight_g is not None else "Weight: not weighed."
    if hand_photo:
        facts += (" This is a hand-held phone photo, so estimate the size. If the printed board is in the "
                  f"photo, use it as a ruler: its four corner markers are {config.MARKER_SPAN_X_CM:g} cm apart "
                  f"across and {config.MARKER_SPAN_Y_CM:g} cm apart lengthwise (centre to centre), and each "
                  f"marker is {config.MARKER_SIZE_CM:g} cm square. Measure the item itself, not the board: "
                  "if it covers markers or sticks out past the board's edges, it is bigger than that frame.")
    elif length_cm is None:
        facts += " Dimensions could not be measured automatically."
    else:
        facts += (f" Measured length: {length_cm} cm, width: {width_cm} cm, "
                  f"top-view area: {area_cm2} cm2.")

    contents = [types.Part.from_bytes(data=photo_jpeg, mime_type="image/jpeg")]
    if annotated_jpeg is not None:
        contents.append(types.Part.from_bytes(data=annotated_jpeg, mime_type="image/jpeg"))
    contents.append(facts + "\nDescribe this piece.")

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        response_mime_type="application/json",
        response_json_schema=SCHEMA,
    )
    # Try each model in turn: on the free tier a model is often busy (503) or
    # over its daily limit (429), and the next one usually still works.
    for i, model in enumerate(models):
        last = i == len(models) - 1
        try:
            response = client.models.generate_content(model=model, contents=contents, config=config)
            break
        except errors.ClientError as e:
            if e.code == 429 and not last:
                continue
            raise ClassificationError(f"Gemini rejected the request ({e.code}): {e.message}") from e
        except errors.APIError as e:
            if not last:
                continue
            raise ClassificationError(f"Gemini error ({e.code}): {e.message}") from e
        except httpx.HTTPError as e:   # timeouts and dropped connections
            if not last:
                continue
            raise ClassificationError(f"could not reach Gemini: {e}") from e

    if not response.text:
        raise ClassificationError("Gemini returned no answer (possibly blocked)")
    try:
        result = json.loads(response.text)
    except json.JSONDecodeError as e:
        raise ClassificationError("Gemini returned invalid JSON") from e
    result["material_confidence"] = min(max(float(result["material_confidence"]), 0.0), 1.0)
    if result.get("disposal") not in DISPOSAL:
        result["disposal"] = "reuse"
    return result
