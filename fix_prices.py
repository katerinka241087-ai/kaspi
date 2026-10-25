from datetime import datetime
import os
import xml.etree.ElementTree as ET
import requests

OUTPUT_XML = "kaspi.xml"
MERCHANT_ID = "30332535"
MIN_STOCK_THRESHOLD = 5
KASPI_API_TOKEN = "WCE/VD+TtNxNtL2IVcanwULSJxjn1vJLjB9EBMHW2zI="
PRICE_STEP = 10
TARIF_PER_KG = 150
TARIF_PER_M3 = 45000

kaspi_headers = {"X-Auth-Token": KASPI_API_TOKEN, "Content-Type": "application/json"}

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

base_file_name = "sima.xml.xml"
if not os.path.exists(base_file_name): 
    exit()

tree = ET.parse(base_file_name)
root = tree.getroot()

products_data = []
for item in root.findall('.//item'):
    sid = item.get('sid') or item.get('id') or item.get('sku')
    price_element = item.find('.//price') or item.find('.//price_ru') or item.find('.//value')
    price = price_element.text if price_element is not None else None
    if sid and price:
        products_data.append((sid.strip(), price.strip()))

if not products_data: 
    exit()

sima_data_dict = {}
sku_only_list = [item for item, _ in products_data]
sima_headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
chunk_size = 50
for i in range(0, len(products_data), chunk_size):
    chunk = sku_only_list[i: i + chunk_size]
    try:
        response = requests.get("https://sima-land.ru", params={"sid": ",".join(chunk)}, headers=sima_headers, timeout=20)
        if response.status_code == 200:
            for item in response.json().get("items", []):
                sid = str(item.get("sid"))
                balance = item.get("balance", 0)
                qty = 20 if isinstance(balance, str) and ("много" in balance.lower() or "достаточно" in balance.lower()) else (3 if isinstance(balance, str) and "мало" in balance.lower() else int(balance))
                sima_data_dict[sid] = {
                    "balance": qty,
                    "weight_kg": float(item.get("weight", 0)) / 1000.0,
                    "volume_m3": float(item.get("box_volume", 0))
                }
    except Exception: 
        pass

current_date = datetime.now().strftime("%d.%m.%Y")
root_kaspi = ET.Element("kaspi_catalog", {"date": current_date, "xmlns": "http://kaspi.kz", "xmlns:xsi": "http://w3.org", "xsi:schemaLocation": "http://kaspi.kz http://kaspi.kz.xsd"})
ET.SubElement(root_kaspi, "company")
merchant_id = ET.SubElement(root_kaspi, "merchantid")
merchant_id.text = MERCHANT_ID
offers_node = ET.SubElement(root_kaspi, "offers")

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

    ET.SubElement(offer_node, "price").text = str(int(final_xml_price))
    availabilities_node = ET.SubElement(offer_node, "availabilities")
    if item_info["balance"] < MIN_STOCK_THRESHOLD:
        ET.SubElement(availabilities_node, "availability", {"available": "no", "storeId": "PP4"})
    else:
        ET.SubElement(availabilities_node, "availability", {"available": "yes", "storeId": "PP4", "preorder": "true", "deliveryTime": "12"})

# Сохранение итогового XML в файл
final_output = ET.tostring(root_kaspi, encoding="utf-8", xml_declaration=True).decode("utf-8")
final_output += f'<!-- Updated at {datetime.now().second} seconds past the minute -->\n'

with open(OUTPUT_XML, "w", encoding="utf-8") as f: 
    f.write(final_output)
