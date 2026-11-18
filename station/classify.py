"""Ask Gemini to describe a scrap piece. Returns a dict that matches SCHEMA."""
import json

import httpx
from google.genai import errors, types

MATERIALS = [
    "acrylic", "pla", "other_plastic", "cardboard", "paper", "wood", "mdf",
    "wire", "metal", "electronics", "fabric", "foam", "glass", "unknown",
]
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
    },
    "required": ["name", "material", "material_confidence", "colour", "condition",
                 "transparency", "estimated_thickness_cm", "suggested_use", "description"],
}

SYSTEM_PROMPT = """You inspect pieces of scrap deposited at a school scrapyard's sorting station.

Each piece lies on a measuring board photographed from directly above. The board \
has a grid labelled in cm and four black-and-white square markers at its corners; \
ignore the markers and grid except as a size reference. You get two images: the raw \
photo, and a straightened top-down view with the detected piece outlined in green \
(red box = measured bounding rectangle).

Length, width, area and weight are measured by instruments and given to you as \
facts - use them, do not re-estimate them. Use them as evidence: weight divided by \
(area x your thickness estimate) gives a density, e.g. acrylic ~1.2 g/cm3, PLA ~1.25, \
cardboard ~0.1-0.7, wood ~0.4-0.8, aluminium ~2.7, steel ~7.8.

"wire" means electrical wire or cable. "pla" means 3D-printed plastic (visible layer \
lines, typical printed shapes). When the evidence does not settle the material, pick \
the most likely option and lower material_confidence, or answer "unknown". An honest \
low confidence is far more useful than a confident wrong answer, because uncertain \
pieces are checked by a person. If grid lines are visible through the piece it is \
transparent or translucent."""


class ClassificationError(Exception):
    pass


def material_label(material: str) -> str:
    return MATERIAL_LABELS.get(material, material.capitalize())


def classify(client, models: list[str], photo_jpeg: bytes, annotated_jpeg: bytes | None,
             weight_g: float, length_cm: float | None, width_cm: float | None,
             area_cm2: float | None) -> dict:
    if client is None:
        raise ClassificationError("Gemini not configured (set GEMINI_API_KEY)")
    if length_cm is None:
        facts = f"Weight: {weight_g:.1f} g. Dimensions could not be measured automatically."
    else:
        facts = (f"Weight: {weight_g:.1f} g. Measured length: {length_cm} cm, "
                 f"width: {width_cm} cm, top-view area: {area_cm2} cm2.")

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
    return result
