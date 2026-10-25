```python
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import html
import json
import logging
import os
import sys
import xml.etree.ElementTree as ET

import requests


# ============================================================
# НАСТРОЙКИ
# ============================================================

BASE_XML = Path("sima.xml.xml")
OUTPUT_XML = Path("kaspi.xml")

MERCHANT_ID = "30332535"
MIN_STOCK_THRESHOLD = 5

PRICE_STEP = 10
TARIF_PER_KG = Decimal("150")
TARIF_PER_M3 = Decimal("45000")

CHUNK_SIZE = 50

# Токен задаётся в GitHub Secrets, а не хранится в исходном коде.
KASPI_API_TOKEN = os.getenv("KASPI_API_TOKEN", "").strip()

# Адреса оставлены такими, как в исходном коде.
SIMA_API_URL = "https://sima-land.ru"
KASPI_API_URL = "https://kaspi.kz"

SIMA_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
}

KASPI_HEADERS = {
    "X-Auth-Token": KASPI_API_TOKEN,
    "Content-Type": "application/json",
}

# Пространства имён и шапка итогового XML.
# Намеренно сохраняем указанный в задании формат.
KASPI_NAMESPACE = "http://kaspi.kz"
XSI_NAMESPACE = "http://w3.org"
KASPI_SCHEMA_URL = "http://kaspi.kz.xsd"


# ============================================================
# ЛОГИРОВАНИЕ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================

def local_name(tag):
    """
    Возвращает локальное имя XML-тега без пространства имён.

    Поддерживает, например:
        price
        {http://example.com/schema}price
        ns0:price
    """
    if not isinstance(tag, str):
        return ""

    if "}" in tag:
        tag = tag.rsplit("}", 1)[-1]

    if ":" in tag:
        tag = tag.rsplit(":", 1)[-1]

    return tag.strip().lower()


def normalize_text(value):
    """Преобразует значение в очищенную строку."""
    if value is None:
        return ""

    return str(value).strip()


def parse_decimal(value):
    """
    Преобразует цену в Decimal.

    Поддерживает:
        1234
        1234.50
        1234,50
        1 234,50
        1 234.50
    """
    text = normalize_text(value)

    if not text:
        return None

    text = (
        text.replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace(",", ".")
    )

    try:
        result = Decimal(text)
    except InvalidOperation:
        return None

    if not result.is_finite() or result < 0:
        return None

    return result


def find_price_in_element(element):
    """
    Ищет цену внутри элемента и его дочерних элементов.

    Названия тегов:
        price
        price_ru
        value
        price_base

    Пространства имён игнорируются.
    """
    price_tags = {
        "price",
        "price_ru",
        "value",
        "price_base",
    }

    for node in element.iter():
        tag = local_name(node.tag)

        if tag not in price_tags:
            continue

        value = parse_decimal(node.text)

        if value is not None:
            return value

        # Некоторые XML-выгрузки хранят значение в атрибуте.
        for attr_name, attr_value in node.attrib.items():
            if local_name(attr_name) in {
                "value",
                "price",
                "amount",
            }:
                value = parse_decimal(attr_value)

                if value is not None:
                    return value

    return None


def find_sku_in_element(element):
    """
    Ищет артикул в атрибутах элемента.

    Приоритет:
        sid
        sku
        id

    Проверяются также атрибуты с пространствами имён.
    """
    sku_attributes = {
        "sid": 0,
        "sku": 1,
        "id": 2,
    }

    candidates = []

    for attr_name, attr_value in element.attrib.items():
        normalized_name = local_name(attr_name)

        if normalized_name not in sku_attributes:
            continue

        value = normalize_text(attr_value)

        if not value:
            continue

        candidates
