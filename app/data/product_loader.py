"""Loader produktów: XML (BaseLinker) lub shared SQLite.

Parser XML używa lxml (learning: iterparse dla dużych plików, ale tu
zakładamy typowe eksporty <100 MB → bezpieczne fromstring/parse).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree  # type: ignore[import-not-found]

from .shared_db import load_from_shared_db

__all__ = ["Product", "load_from_xml", "load_from_shared_db_typed"]


@dataclass
class Product:
    """Znormalizowany rekord produktu.

    Uwaga: `ean` walidowany osobno (gs1-ean-management). Tu tylko przechowujemy.
    """

    sku: str
    name: str
    category: str = ""
    price: float = 0.0
    ean: str = ""
    image_urls: list[str] = field(default_factory=list)
    description: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Product":
        return cls(
            sku=str(data.get("sku") or data.get("id") or "").strip(),
            name=str(data.get("name") or data.get("title") or "").strip(),
            category=str(data.get("category") or "").strip(),
            price=_to_float(data.get("price")),
            ean=str(data.get("ean") or "").strip(),
            image_urls=_to_list(data.get("image_urls") or data.get("images")),
            description=str(data.get("description") or "").strip(),
        )


def _to_float(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        # Obsługuje "129,90" i "129.90"
        return float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return 0.0


def _to_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        # Rozdziel po pipe/przecinku/nowej linii (typowe formaty XML feed).
        parts = [p.strip() for p in v.replace("|", ",").split(",")]
        return [p for p in parts if p]
    return []


def load_from_xml(xml_path: Path) -> list[Product]:
    """Parsuje BaseLinker-style XML z hurtowni.

    Zakładany schemat (tolerancyjny — ignoruje nieznane pola):

    ```xml
    <offer>
      <offers>
        <o id="ABC1">
          <name>Sofa narożna Beata</name>
          <category>Meble > Salon > Sofy</category>
          <price>899.00</price>
          <attrs><a name="EAN">5901234567890</a></attrs>
          <imgs>
            <main url="https://..."/>
            <i url="https://..."/>
          </imgs>
          <desc><![CDATA[Opis...]]></desc>
        </o>
      </offers>
    </offer>
    ```

    Rzuca ``FileNotFoundError`` gdy plik nie istnieje.
    """
    xml_path = Path(xml_path).expanduser()
    if not xml_path.is_file():
        raise FileNotFoundError(f"XML nie istnieje: {xml_path}")

    parser = etree.XMLParser(
        resolve_entities=False,  # bezpieczeństwo (XXE)
        no_network=True,
        recover=True,             # toleruj drobne błędy w feedzie
        huge_tree=False,
    )
    tree = etree.parse(str(xml_path), parser=parser)
    root = tree.getroot()

    products: list[Product] = []
    # Elastyczna ścieżka — BaseLinker warianty: <o>, <offer>, <product>.
    offer_nodes = root.xpath(".//o | .//offer | .//product")
    for node in offer_nodes:
        sku = (
            node.get("id")
            or _text(node, "sku")
            or _text(node, "id")
            or ""
        ).strip()
        if not sku:
            continue

        product = Product(
            sku=sku,
            name=_text(node, "name") or _text(node, "title"),
            category=_text(node, "category") or _text(node, "cat"),
            price=_to_float(_text(node, "price")),
            ean=_extract_ean(node),
            image_urls=_extract_images(node),
            description=_text(node, "desc") or _text(node, "description"),
        )
        products.append(product)

    return products


def _text(node: Any, tag: str) -> str:
    """Zwraca stripped text pierwszego child z tego tagu (case-insensitive), lub ''."""
    matches = node.xpath(f"./*[translate(local-name(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')=$t]", t=tag.lower())
    if not matches:
        return ""
    txt = matches[0].text
    return (txt or "").strip()


def _extract_ean(node: Any) -> str:
    """Szuka EAN w <attrs><a name="EAN"> lub bezpośrednim <ean>."""
    direct = _text(node, "ean")
    if direct:
        return direct
    attrs = node.xpath(".//a[@name='EAN' or @name='ean']")
    if attrs:
        return (attrs[0].text or "").strip()
    return ""


def _extract_images(node: Any) -> list[str]:
    """Zwraca listę URLi obrazów. Obsługuje <imgs><main url=...>, <i url=...>, <image>."""
    urls: list[str] = []
    for img in node.xpath(".//imgs/*[self::main or self::i or self::image]"):
        url = (img.get("url") or img.text or "").strip()
        if url:
            urls.append(url)
    if not urls:
        for img in node.xpath(".//image | .//img"):
            url = (img.get("url") or img.get("src") or img.text or "").strip()
            if url:
                urls.append(url)
    return urls


def load_from_shared_db_typed(limit: int | None = None) -> list[Product]:
    """Wrapper zwracający Product zamiast dict. Read-only z tabeli products."""
    rows = load_from_shared_db(limit=limit)
    return [Product.from_dict(r) for r in rows]
