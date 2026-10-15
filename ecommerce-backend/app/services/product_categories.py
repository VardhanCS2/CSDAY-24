import re
from collections.abc import Iterable

CATEGORY_DEFINITIONS: tuple[dict[str, str], ...] = (
    {"name": "Electronics", "icon": "laptop"},
    {"name": "Footwear", "icon": "footprints"},
    {"name": "Clothing", "icon": "shirt"},
    {"name": "Home & Kitchen", "icon": "cooking-pot"},
    {"name": "Furniture", "icon": "armchair"},
    {"name": "Books & Stationery", "icon": "book-open"},
    {"name": "Consoles & Video Games", "icon": "gamepad"},
    {"name": "Accessories", "icon": "watch"},
    {"name": "Other", "icon": "shapes"},
)

_CATEGORY_BY_NORMALIZED_NAME = {
    " ".join(re.findall(r"[a-z0-9]+", category["name"].casefold())): category["name"]
    for category in CATEGORY_DEFINITIONS
}
_CATEGORY_ALIASES = {
    "electronic": "Electronics",
    "electronics": "Electronics",
    "mobile": "Electronics",
    "mobiles": "Electronics",
    "phone": "Electronics",
    "phones": "Electronics",
    "smartphone": "Electronics",
    "smartphones": "Electronics",
    "laptop": "Electronics",
    "laptops": "Electronics",
    "computer": "Electronics",
    "computers": "Electronics",
    "shoe": "Footwear",
    "shoes": "Footwear",
    "sneaker": "Footwear",
    "sneakers": "Footwear",
    "boot": "Footwear",
    "boots": "Footwear",
    "sandal": "Footwear",
    "sandals": "Footwear",
    "apparel": "Clothing",
    "clothes": "Clothing",
    "garments": "Clothing",
    "home": "Home & Kitchen",
    "kitchen": "Home & Kitchen",
    "decor": "Home & Kitchen",
    "cookware": "Home & Kitchen",
    "chair": "Furniture",
    "chairs": "Furniture",
    "stool": "Furniture",
    "stools": "Furniture",
    "table": "Furniture",
    "tables": "Furniture",
    "sofa": "Furniture",
    "sofas": "Furniture",
    "desk": "Furniture",
    "desks": "Furniture",
    "book": "Books & Stationery",
    "books": "Books & Stationery",
    "stationery": "Books & Stationery",
    "console": "Consoles & Video Games",
    "consoles": "Consoles & Video Games",
    "game": "Consoles & Video Games",
    "games": "Consoles & Video Games",
    "bag": "Accessories",
    "bags": "Accessories",
    "watch": "Accessories",
    "watches": "Accessories",
    "jewellery": "Accessories",
    "jewelry": "Accessories",
    "miscellaneous": "Other",
    "others": "Other",
    "general": "Other",
    "console": "Consoles & Video Games",
    "gaming console": "Consoles & Video Games",
}


def product_categories() -> list[dict[str, str]]:
    return [dict(category) for category in CATEGORY_DEFINITIONS]


def canonicalize_product_categories(categories: Iterable[str]) -> list[str]:
    canonical: list[str] = []
    for category in categories:
        normalized = " ".join(re.findall(r"[a-z0-9]+", category.casefold()))
        value = _CATEGORY_BY_NORMALIZED_NAME.get(normalized)
        if value is None and " " not in normalized:
            value = _CATEGORY_ALIASES.get(normalized)
        if value is None:
            raise ValueError(f"Unsupported product category: {category}")
        if value not in canonical:
            canonical.append(value)
    if len(canonical) > 3:
        raise ValueError("A product can have no more than 3 categories.")
    return canonical


def category_terms(category: str) -> tuple[str, ...]:
    return (canonicalize_product_categories([category])[0],)
