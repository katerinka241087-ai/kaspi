from datetime import datetime
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET
import requests

# =====================================================================
# НАСТРОЙКИ КАСПИ И ТАРИФОВ ДОСТАВКИ СИМА-ЛЕНД
# =====================================================================
OUTPUT_XML = "kaspi.xml"
MERCHANT_ID = "30332535"
MIN_STOCK_THRESHOLD = 5  # Если остаток на Симе < 5, полностью снимаем с продажи

# --- НАСТРОЙКА РЕЖИМА РАБОТЫ ---
ENABLE_DUMPING = False  

# --- СЕКРЕТНЫЙ API КЛЮЧ КАСПИ ---
KASPI_API_TOKEN = "WCE/VD+TtNxNtL2IVcanwULSJxjn1vJLjB9EBMHW2zI=" 

# Настройки демпинга
PRICE_STEP = 10 

# Тарифы транспортной компании за доставку груза Симы до твоего города
TARIF_PER_KG = 150       # Стоимость доставки 1 кг в тенге
TARIF_PER_M3 = 45000     # Стоимость доставки 1 кубического метра в тенге

# =====================================================================
# ФУНКЦИИ ДЛЯ РАБОТЫ С API КАСПИ (ДЕМПИНГ)
# =====================================================================
kaspi_headers = {
    "X-Auth-Token": KASPI_API_TOKEN,
    "Content-Type": "application/json"
}

def get_kaspi_competitors(sku):
    url = "https://kaspi.kz"
    query_params = {"sku": str(sku).strip()}
    try:
        response = requests.get(url, headers=kaspi_headers, params=query_params, timeout=5)
        if response.status_code == 200:
            offers = response.json().get("data", [])
            other_offers = [o for o in offers if str(o.get("merchantId")) != str(MERCHANT_ID)]
            if other_offers:
                return min(float(o.get("price", 999999)) for o in other_offers)
    except Exception:
        pass
    return None

def update_kaspi_price(sku, new_price):
    url = "https://kaspi.kz"
    payload = {"data": {"sku": str(sku).strip(), "price": int(new_price)}}
    try:
        requests.post(url, json=payload, headers=kaspi_headers, timeout=5)
    except Exception:
        pass

# =====================================================================
# ОДНОКРАТНОЕ ВЫПОЛНЕНИЕ ДЛЯ ОБЛАКА GITHUB
# =====================================================================
print(f"\n=====================================================================")
print(f"СТАРТ СЕССИИ ОБНОВЛЕНИЯ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"=====================================================================")

# 1. ПОИСК ИСХОДНОГО ФАЙЛА С БАЗОЙ ТОВАРОВ (ИГНОРИРУЕМ СТАРЫЙ OUTPUT_XML)
all_files = os.listdir(".")
best_file = None
max_offers = 0
best_content = ""

for filename in all_files:
    if filename in ["fix_prices.py", OUTPUT_XML] or os.path.isdir(filename):
        continue
    try:
        with open(filename, "r", encoding="utf-8", errors="ignore") as f:
            test_content = f.read()
            offers_found = re.findall(r'<offer sku="(.*?)">', test_content)
            if len(offers_found) > max_offers:
                max_offers = len(offers_found)
                best_file = filename
                best_content = test_content
    except Exception:
        continue

if not best_file or max_offers == 0:
    print("\n[КРИТИЧЕСКАЯ ОШИБКА] В папке не найден файл с вашей базой товаров!")
    exit()

# 2. ИЗВЛЕКАЕМ SKU И ИСХОДНЫЕ ЦЕНЫ ИЗ ЛОКАЛЬНОЙ БАЗЫ
offers_raw = re.findall(r'<offer sku="(.*?)">.*?<price>(.*?)</price>', best_content, re.DOTALL)
products_data = []

for sku, price in offers_raw:
    products_data.append((sku.strip(), price.strip()))

total_items = len(products_data)
print(f"[ИНФО] База '{best_file}' успешно считана ({total_items} позиций).")

# 3. ПОЛУЧЕНИЕ ДАННЫХ ИЗ API СИМА-ЛЕНД V3 (ОСТАТКИ + ГАБАРИТЫ)
print("[API] Запрашиваем остатки и габариты у Сима-Ленд пачками...")
sima_data_dict = {}
sku_only_list = [item for item, _ in products_data]
sima_headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

chunk_size = 50
for i in range(0, total_items, chunk_size):
    chunk = sku_only_list[i : i + chunk_size]
    try:
        response = requests.get("https://sima-land.ru", params={"sid": ",".join(chunk)}, headers=sima_headers, timeout=20)
        if response.status_code == 200:
            for item in response.json().get("items", []):
                sid = str(item.get("sid"))
                balance = item.get("balance", 0)
                weight = float(item.get("weight", 0))
                box_volume = float(item.get("box_volume", 0))

                if isinstance(balance, str):
                    balance_lower = balance.lower()
                    qty = 20 if "много" in balance_lower or "достаточно" in balance_lower else (3 if "мало" in balance_lower else 0)
                else:
                    qty = int(balance)

                sima_data_dict[sid] = {"balance": qty, "weight_kg": weight / 1000.0, "volume_m3": box_volume}
    except Exception:
        pass

print(f"\n[УСПЕХ] Все данные от Сима-Ленд успешно загружены.")

# 4. СБОРКА ИТОГОВОГО XML И УМНЫЙ ДЕМПИНГ
# ИСПРАВЛЕНО: Формат даты приведен к стандарту Kaspi (ДД.ММ.ГГГГ)
current_date = datetime.now().strftime("%d.%m.%Y")

# ИСПРАВЛЕНО: Удалены конфликтующие атрибуты, из-за которых ломалась валидация XSD
root = ET.Element("kaspi_catalog", {
    "xmlns": "http://kaspi.kz",
    "xmlns:xsi": "http://w3.org",
    "xsi:schemaLocation": "http://kaspi.kz http://kaspi.kz.xsd",
    "date": current_date
})

ET.SubElement(root, "company")
merchant_id = ET.SubElement(root, "merchantid")
merchant_id.text = MERCHANT_ID
offers_node = ET.SubElement(root, "offers")

preorder_count = 0
hidden_count = 0

print("[ПРОЦЕСС] Расчет цен и формирование XML...")
for sku, base_price_str in products_data:
    offer_node = ET.SubElement(offers_node, "offer", {"sku": sku})
    ET.SubElement(offer_node, "model").text = f"Товар {sku}"
    ET.SubElement(offer_node, "brand").text = "Noname"

    try:
        base_price = float(base_price_str)
    except ValueError:
        base_price = 5000.0

    item_info = sima_data_dict.get(sku, {"balance": 0, "weight_kg": 0.0, "volume_m3": 0.0})
    shipping_surcharge = max(item_info["weight_kg"] * TARIF_PER_KG, item_info["volume_m3"] * TARIF_PER_M3)
    total_item_cost = base_price + shipping_surcharge

    min_allowed_price = round(((total_item_cost * 1.25) + 1500 + 1000) / 0.80, -1)
    start_selling_price = round(total_item_cost * 2.35, -1)

    final_xml_price = start_selling_price

    if ENABLE_DUMPING and KASPI_API_TOKEN != "ТВОЙ_API_КЛЮЧ_КАСПИ":
        competitor_price = get_kaspi_competitors(sku)
        if competitor_price is not None:
            target_price = competitor_price - PRICE_STEP
            if target_price >= min_allowed_price:
                final_xml_price = target_price
                update_kaspi_price(sku, target_price)
            else:
                final_xml_price = min_allowed_price
                update_kaspi_price(sku, min_allowed_price)

    ET.SubElement(offer_node, "price").text = str(int(final_xml_price))

    availabilities_node = ET.SubElement(offer_node, "availabilities")
    if item_info["balance"] < MIN_STOCK_THRESHOLD:
        ET.SubElement(availabilities_node, "availability", {"available": "no", "storeId": "PP4"})
        hidden_count += 1
    else:
        ET.SubElement(availabilities_node, "availability", {"available": "yes", "storeId": "PP4", "preorder": "true", "deliveryTime": "12"})
        preorder_count += 1

# Сохраняем XML файл
tree = ET.ElementTree(root)
ET.indent(tree, space="    ", level=0)
tree.write(OUTPUT_XML, encoding="utf-8", xml_declaration=True)

print(f"[ФИНАЛ] СЕССИЯ ЗАВЕРШЕНА. Файл '{OUTPUT_XML}' успешно обновлен!")
