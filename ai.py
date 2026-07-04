import base64
import json
import mimetypes
import os
import re
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", OPENAI_MODEL)

_client = None
if OPENAI_API_KEY and not OPENAI_API_KEY.startswith("sk-your-openai-api-key"):
    try:
        from openai import OpenAI

        _client = OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        _client = None


def vision_ocr_available() -> bool:
    return _client is not None


def vision_ocr(image_path: str) -> str:
    if _client is None:
        raise AIAnalysisError("OpenAI client is not configured for image OCR.")

    try:
        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        with open(image_path, "rb") as f:
            b64_image = base64.b64encode(f.read()).decode("utf-8")
    except OSError as exc:
        raise AIAnalysisError(f"Could not read the uploaded image file: {exc}") from exc

    try:
        response = _client.chat.completions.create(
            model=OPENAI_VISION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You transcribe text from photos of food ingredient "
                        "labels exactly as written. Output plain text only "
                        "(no markdown, no commentary), preserving words like "
                        "'Ingredients:' if present."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Transcribe all readable text from this food "
                                "label photo, focusing on the ingredients list."
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64_image}"},
                        },
                    ],
                },
            ],
            temperature=0,
        )
    except Exception as exc:
        raise AIAnalysisError(f"AI vision OCR failed: {exc}") from exc

    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise AIAnalysisError("AI vision could not read any text from this image.")
    return text

SYSTEM_PROMPT = """You are NutriLens AI, a nutrition-education assistant.
You explain food ingredients in clear, in-depth, and completely NEUTRAL
language so an average shopper can understand what each ingredient is and
why it's in the product - similar in tone to a food-science reference or
encyclopedia entry, not a viral health article.

You MUST follow these rules at all times:
- Explain ingredients neutrally and factually. Describe what something is,
  where it typically comes from, and its common role in food.
- Avoid fearmongering, dramatic, or alarmist language (e.g. do not call
  ingredients "toxic", "poison", "chemical", or "bad" - describe their
  function instead).
- Avoid medical claims of any kind (do not claim an ingredient causes,
  cures, prevents, or is linked to any disease or health condition).
- Never diagnose, assess, or make personalized health judgments about the
  user reading this. You know nothing about them.
- Never claim an ingredient is "dangerous", "unsafe", or "harmful" - if an
  ingredient is commonly discussed for moderation (e.g. added sugars,
  sodium, certain additives), describe that neutrally and factually
  (e.g. "contributes to the product's total added sugar content") without
  asserting harm.
- You are not a doctor, dietitian, or regulator, and must not claim
  scientific certainty. Present this as general food-literacy education.
- Be thorough and specific rather than generic - avoid vague filler like
  "this ingredient adds flavor" without saying what it actually is or does.
- Be honest and appropriately critical when scoring. The absence of scary-
  sounding chemicals does NOT make a food deserve a high score. Refined
  grains/flours, added sugars, added sodium, and fried/added oils should
  meaningfully lower a score even when nothing is a shocking additive.
  Reserve high scores (90-100) for genuinely whole, minimally-combined
  foods, not for typical packaged snacks (crackers, chips, cookies, sugary
  cereal, etc.) - those should generally land in the middle-to-lower range.

Always respond with strict JSON matching the requested schema.
"""

JSON_SCHEMA_INSTRUCTIONS = """
Return ONLY a JSON object with this exact shape (no markdown, no commentary):

{
  "product_title": "A short, neutral, descriptive title for this product based on its ingredients (e.g. 'Sweetened Cocoa Spread'), used only if no product name was given",
  "product_summary": "An actual, well-written 4-6 sentence summary of THIS SPECIFIC PRODUCT - describe what kind of food/drink it is, its likely taste/texture/category (e.g. 'a baked, cheese-flavored wheat cracker snack'), what its ingredient list is mainly composed of (e.g. refined grains, added oils, dairy, sweeteners), and its general processing level - written like a real product description, NOT meta-commentary about how the summary was generated",
  "processing_level": "One of: Minimally Processed, Processed, Highly Processed, Ultra-Processed",
  "pros": ["3-5 specific, factual, neutrally-worded positive observations", "..."],
  "cons": ["3-5 specific, factual, neutrally-worded points to be aware of (not alarmist)", "..."],
  "alternatives": ["Only if processing_level is NOT 'Minimally Processed': 3-4 specific, realistic, less-processed alternative foods or swaps a shopper could choose instead (e.g. 'Plain roasted almonds instead of a flavored snack mix', 'Homemade version using whole ingredients you control'). Leave this as an empty array if processing_level is 'Minimally Processed'.", "..."],
  "ingredients": [
    {
      "name": "Ingredient name",
      "explanation": "2-3 sentences: what this ingredient actually is (e.g. its source or how it's typically produced) explained neutrally and in depth",
      "purpose": "1-2 sentences on its common role in foods generally AND specifically why it's likely used in this product"
    }
  ],
  "scores": {
    "overall": 0,
    "processing": 0,
    "ingredient": 0
  }
}

Scoring guidance (0 = worst, 100 = best; these are simple educational estimates,
NOT scientifically validated measurements). Be realistic and critical - do
NOT default to high scores just because nothing is a shocking chemical.
Use these calibration anchors as a rough guide:
- 90-100: Genuinely whole, single- or few-ingredient foods (e.g. plain
  fruit/vegetables, plain oats, water) with no refined ingredients.
- 70-89: Simple, mostly-recognizable ingredients, minimal refined flour/
  sugar/oil, no notable additives.
- 50-69: Everyday "processed" food - contains refined grains/flour, added
  sugar, added oil, and/or a couple of common additives, but nothing
  extreme (this is where most typical packaged snacks and baked goods
  usually belong).
- 30-49: "Highly processed" food - several additives/preservatives and/or
  significant refined ingredients, added sugar, sodium, or oil (e.g. most
  crackers, chips, cookies, sweetened cereal).
- 0-29: "Ultra-processed" food - long ingredient list dominated by
  additives, artificial colors/flavors, preservatives, and/or very high
  added sugar/sodium/fat.
- "processing" reflects how minimally processed the product is.
- "ingredient" reflects the overall quality/simplicity of the ingredient list.
- "overall" is a blended impression of the two.
List every ingredient provided, in the same order, without skipping any.
Remember: neutral and factual throughout - no fearmongering, no medical
claims, no diagnosing the reader, and never call an ingredient "dangerous".

Alternatives (IMPORTANT, do not skip this): If "processing_level" is
"Processed", "Highly Processed", or "Ultra-Processed" (i.e. anything other
than "Minimally Processed"), the "alternatives" array MUST contain exactly
3-4 specific, realistic, less-processed alternative foods or product swaps
a shopper could choose instead (e.g. "Plain roasted almonds instead of a
flavored snack mix", "A homemade version using whole ingredients you
control"). Only leave "alternatives" as an empty array when
"processing_level" is exactly "Minimally Processed". Keep suggestions
neutral, factual, and practical - not alarmist, preachy, or phrased as
medical advice.
"""


class AIAnalysisError(Exception):
    pass


def _build_user_prompt(ingredients_text: str, product_name: Optional[str]) -> str:
    name_part = f'Product name: "{product_name}"\n' if product_name else ""
    return (
        f"{name_part}"
        f"Ingredients list (as extracted from the label):\n{ingredients_text}\n\n"
        f"{JSON_SCHEMA_INSTRUCTIONS}"
    )


def _call_openai(ingredients_text: str, product_name: Optional[str]) -> Dict[str, Any]:
    if _client is None:
        raise AIAnalysisError("OpenAI client is not configured.")

    response = _client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(ingredients_text, product_name)},
        ],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    content = response.choices[0].message.content
    return json.loads(content)


_ULTRA_PROCESSED_MARKERS = [
    "sodium benzoate", "potassium sorbate", "high fructose corn syrup",
    "artificial flavor", "artificial color", "monosodium glutamate", "msg",
    "hydrogenated", "corn syrup", "red 40", "yellow 5", "yellow 6", "blue 1",
    "aspartame", "sucralose", "maltodextrin", "modified starch",
    "sodium nitrite", "bha", "bht", "carrageenan", "propylene glycol",
    "polysorbate", "xanthan gum", "soy lecithin", "natural flavor",
]

_REFINED_MARKERS = [
    "enriched flour", "bleached flour", "white flour", "wheat flour",
    "enriched wheat", "corn starch", "dextrose", "invert sugar",
    "cane sugar", "brown sugar", "vegetable oil", "palm oil", "canola oil",
    "soybean oil", "sunflower oil", "shortening", "cheese culture", "salt",
    "sugar", "syrup", "starch",
]

_WHOLE_FOOD_MARKERS = [
    "water", "whole wheat", "rice", "oat", "egg", "butter", "olive oil",
    "tomato", "onion", "garlic", "pepper", "vinegar", "yeast", "honey",
    "potato", "fruit", "vegetable",
]


def _split_ingredients(ingredients_text: str) -> List[str]:
    parts = re.split(r",|;", ingredients_text)
    return [p.strip() for p in parts if p.strip()]


def _default_alternatives() -> List[str]:
    return [
        "A version of this product with a shorter ingredient list and "
        "fewer additives, if available from the same brand or a competitor.",
        "A homemade version made from whole ingredients you choose and "
        "control directly.",
        "A plain, single-ingredient whole food (e.g. fresh fruit, plain "
        "nuts, or plain yogurt) as a less-processed snack option.",
    ]


def derive_title_from_ingredients(ingredients_text: str, max_length: int = 80) -> str:
    names = _split_ingredients(ingredients_text)
    if not names:
        return "Scanned Product"
    preview = ", ".join(names[:3])
    if len(names) > 3:
        preview += ", ..."
    if len(preview) > max_length:
        preview = preview[: max_length - 3].rstrip(", ") + "..."
    return preview


def _heuristic_ingredient_info(name: str) -> Dict[str, str]:
    lowered = name.lower()
    if any(marker in lowered for marker in _ULTRA_PROCESSED_MARKERS):
        explanation = (
            f"{name} is a food additive commonly used in packaged and "
            "processed foods. It is typically manufactured rather than "
            "derived directly from a whole food. Configure an OpenAI API "
            "key for a more detailed, ingredient-specific explanation."
        )
        purpose = (
            "Commonly used as a preservative, flavoring, coloring, or "
            "texture agent to extend shelf life or maintain consistency."
        )
    else:
        explanation = (
            f"{name} is a common food ingredient often found in everyday "
            "recipes and packaged foods. Configure an OpenAI API key to get "
            "a more detailed, ingredient-specific explanation of its source "
            "and how it's typically produced."
        )
        purpose = (
            "Generally contributes to the taste, texture, appearance, or "
            "nutritional content of the product."
        )
    return {"name": name, "explanation": explanation, "purpose": purpose}


def _heuristic_analysis(ingredients_text: str, product_name: Optional[str]) -> Dict[str, Any]:
    names = _split_ingredients(ingredients_text) or [ingredients_text.strip()]
    lowered_full = ingredients_text.lower()
    count = len(names)

    ultra_hits = sum(1 for m in _ULTRA_PROCESSED_MARKERS if m in lowered_full)
    refined_hits = sum(1 for m in _REFINED_MARKERS if m in lowered_full)
    whole_hits = sum(1 for m in _WHOLE_FOOD_MARKERS if m in lowered_full)

    if count <= 3:
        count_penalty, count_cap = 0, 100
    elif count <= 5:
        count_penalty, count_cap = 5, 90
    elif count <= 8:
        count_penalty, count_cap = 15, 75
    elif count <= 12:
        count_penalty, count_cap = 25, 60
    else:
        count_penalty, count_cap = 35, 45

    base = 100 - count_penalty
    base -= ultra_hits * 14
    base -= refined_hits * 6
    base += min(whole_hits, 4) * 3

    hard_cap = count_cap
    if ultra_hits > 0:
        hard_cap = min(hard_cap, 55)
    elif refined_hits > 0:
        hard_cap = min(hard_cap, 78)

    ingredient_score = max(0, min(hard_cap, round(base + 4)))
    processing_score = max(0, min(hard_cap, round(base - 4)))
    overall_score = round((ingredient_score + processing_score) / 2)

    if overall_score >= 75:
        level = "Minimally Processed"
    elif overall_score >= 50:
        level = "Processed"
    elif overall_score >= 25:
        level = "Highly Processed"
    else:
        level = "Ultra-Processed"

    pros = []
    cons = []
    if whole_hits > 0:
        pros.append(
            f"Includes {whole_hits} recognizable, whole-food-style ingredient(s) "
            "commonly found in home cooking."
        )
    if ultra_hits == 0:
        pros.append(
            "No ingredients matching common ultra-processed additive keywords "
            "were detected in this basic check."
        )
    if count <= 5:
        pros.append("Relatively short ingredient list compared to many packaged foods.")
    if not pros:
        pros.append("Ingredient list is available in full for your own review.")

    if ultra_hits > 0:
        cons.append(
            f"Contains {ultra_hits} ingredient(s) that match keywords commonly "
            "associated with food additives (e.g. preservatives, colors, or "
            "flavor enhancers)."
        )
    if refined_hits > 0:
        cons.append(
            f"Contains {refined_hits} refined ingredient(s) (e.g. refined flour, "
            "added oils, added sugar, or added sodium) typical of packaged and "
            "snack foods."
        )
    if count > 8:
        cons.append(
            f"Ingredient list has {count} items, which is on the longer side "
            "and typically indicates a more formulated/processed product."
        )
    if not cons:
        cons.append("No notable patterns were flagged by this basic keyword check.")

    alternatives = _default_alternatives() if level != "Minimally Processed" else []

    lead_items = ", ".join(names[:3]) + (", and other ingredients" if count > 3 else "")
    composition_bits = []
    if refined_hits > 0:
        composition_bits.append("refined ingredients such as flour, oils, sugar, or salt")
    if ultra_hits > 0:
        composition_bits.append("one or more common food-additive ingredients")
    if whole_hits > 0:
        composition_bits.append("some recognizable whole-food-style ingredients")
    composition_text = (
        "; it includes " + ", and ".join(composition_bits) + "."
        if composition_bits
        else "."
    )

    return {
        "product_title": derive_title_from_ingredients(ingredients_text),
        "product_summary": (
            f"{product_name or 'This product'} lists {count} ingredient(s), led by "
            f"{lead_items}{composition_text} Based on this ingredient list, it "
            f"falls into the '{level.lower()}' category. (This summary was generated "
            f"by a basic keyword check rather than full AI analysis - configure an "
            f"OpenAI API key in the backend .env file for a richer, written product "
            f"description.)"
        ),
        "processing_level": level,
        "pros": pros,
        "cons": cons,
        "alternatives": alternatives,
        "ingredients": [_heuristic_ingredient_info(n) for n in names],
        "scores": {
            "overall": overall_score,
            "processing": processing_score,
            "ingredient": ingredient_score,
        },
    }


def _validate_and_normalize(result: Dict[str, Any], ingredients_text: str = "") -> Dict[str, Any]:
    result.setdefault("product_title", "")
    if not str(result.get("product_title") or "").strip() and ingredients_text:
        result["product_title"] = derive_title_from_ingredients(ingredients_text)
    result.setdefault("product_summary", "")
    result.setdefault("processing_level", "Processed")
    result.setdefault("pros", [])
    result.setdefault("cons", [])
    result.setdefault("ingredients", [])
    if result.get("processing_level") == "Minimally Processed":
        result["alternatives"] = []
    else:
        if not result.get("alternatives"):
            result["alternatives"] = _default_alternatives()
    scores = result.setdefault("scores", {})
    for key in ("overall", "processing", "ingredient"):
        try:
            value = int(round(float(scores.get(key, 50))))
        except (TypeError, ValueError):
            value = 50
        scores[key] = max(0, min(100, value))
    result["disclaimer"] = (
        "This analysis is generated by AI for educational purposes only. "
        "It is not medical or scientific advice."
    )
    return result


def analyze_ingredients(
    ingredients_text: str, product_name: Optional[str] = None
) -> Dict[str, Any]:
    ingredients_text = (ingredients_text or "").strip()
    if not ingredients_text:
        raise AIAnalysisError("No ingredients text was provided to analyze.")

    if _client is not None:
        try:
            result = _call_openai(ingredients_text, product_name)
            return _validate_and_normalize(result, ingredients_text)
        except Exception:
            pass

    return _validate_and_normalize(
        _heuristic_analysis(ingredients_text, product_name), ingredients_text
    )
