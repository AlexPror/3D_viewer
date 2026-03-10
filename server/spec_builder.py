from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

# Подключаем справочник масс из spec_src
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SPEC_SRC = os.path.join(BASE_DIR, "..", "spec_src", "src")
if os.path.isdir(SPEC_SRC) and SPEC_SRC not in sys.path:
  sys.path.insert(0, SPEC_SRC)

try:
  from core.materials_database import calculate_mass  # type: ignore
except Exception:  # pragma: no cover - fallback, если spec_src не найден
  def calculate_mass(name: str, volume_m3: float = 0.0, length_m: float = 0.0) -> tuple[float, str]:
    return 0.0, "spec_src_not_available"


NO_DATA = "нет данных"


@dataclass
class SpecificationItem:
  designation: str
  name: str
  description: str
  quantity: float
  mass_unit: float
  mass_total: float
  section: str
  material: str = NO_DATA
  note: str = ""


def determine_section(name: str, designation: str) -> str:
  """Определение раздела (Оболочка, Закладные, Стандартные, Покупные, Каркас)."""
  name_lower = (name or "").lower()

  if any(w in name_lower for w in ["оболочка", "панель фасадная", "облицовка"]):
    return "Оболочка"
  if any(w in name_lower for w in ["закладная", "закладной"]):
    return "Закладные детали"
  if any(w in name_lower for w in ["болт", "гайка", "шайба", "заклепка", "винт"]):
    return "Стандартные изделия"
  if any(w in name_lower for w in ["теплообменник", "вентилятор", "блок питания"]):
    return "Покупные изделия"
  return "Каркас модуля"


def designation_base(designation: str) -> str:
  """Базовое обозначение без -01/-02 и исполнений 01."""
  if not designation or designation == NO_DATA:
    return ""
  s = str(designation).strip()
  s = re.sub(r"-\d+$", "", s)  # убрать суффикс -01/-02 в конце
  s = re.sub(r"[.\s]01\b", "", s)  # убрать .01 или 01
  return s


def normalize_name_for_grouping(name: str) -> str:
  """Нормализация имени: кириллическая М/м = латинская M/m (60М = 60M)."""
  if not name:
    return ""
  return name.replace("\u041c", "M").replace("\u043c", "m")


def group_items(items: List[SpecificationItem]) -> List[SpecificationItem]:
  """
  Группировка одинаковых элементов и подсчёт количества.
  Ключ: (нормализованное наименование, базовое обозначение).
  """
  grouped: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(lambda: {"item": None, "count": 0.0})

  for it in items:
    name_key = normalize_name_for_grouping(it.name or "")
    base_des = designation_base(it.designation)
    key = (name_key, base_des)

    if grouped[key]["item"] is None:
      grouped[key]["item"] = SpecificationItem(
        designation=it.designation,
        name=it.name,
        description=it.description,
        quantity=0.0,
        mass_unit=it.mass_unit,
        mass_total=0.0,
        section=it.section,
        material=it.material,
        note=it.note,
      )
    else:
      ref: SpecificationItem = grouped[key]["item"]
      if it.mass_unit > 0 and ref.mass_unit == 0:
        ref.mass_unit = it.mass_unit
      if it.material != NO_DATA and ref.material == NO_DATA:
        ref.material = it.material
      if it.designation and it.designation != NO_DATA and not it.designation.startswith("-"):
        if not ref.designation or ref.designation == NO_DATA or ref.designation.startswith("-"):
          ref.designation = it.designation
          if it.note:
            ref.note = it.note

    grouped[key]["count"] += it.quantity

  result: List[SpecificationItem] = []
  for data in grouped.values():
    ref: SpecificationItem = data["item"]
    qty = float(data["count"])
    ref.quantity = qty
    ref.mass_total = qty * ref.mass_unit
    result.append(ref)

  result.sort(key=lambda x: (x.designation or "", x.name or ""))
  return result


# ГОСТ 2.106-96: порядок разделов спецификации
GOST_SECTION_ORDER = [
  "Документация",
  "Комплексы",
  "Сборочные единицы",
  "Детали",
  "Стандартные изделия",
  "Прочие изделия",
  "Материалы",
  "Комплекты",
]

# Маппинг внутренних разделов в разделы по ГОСТ 2.106-96
INTERNAL_TO_GOST: Dict[str, str] = {
  "Оболочка": "Детали",
  "Каркас модуля": "Детали",
  "Закладные детали": "Детали",
  "Стандартные изделия": "Стандартные изделия",
  "Покупные изделия": "Прочие изделия",
  "Материалы": "Материалы",
}


def group_by_section(items: List[SpecificationItem]) -> Dict[str, List[SpecificationItem]]:
  """Группировка по разделам в порядке ГОСТ 2.106-96."""
  sections: Dict[str, List[SpecificationItem]] = defaultdict(list)
  for it in items:
    sections[it.section].append(it)

  # Объединяем в разделы ГОСТ
  gost_sections: Dict[str, List[SpecificationItem]] = defaultdict(list)
  for internal_name, item_list in sections.items():
    gost_name = INTERNAL_TO_GOST.get(internal_name, "Детали")
    gost_sections[gost_name].extend(item_list)

  ordered: Dict[str, List[SpecificationItem]] = {}
  for name in GOST_SECTION_ORDER:
    if name in gost_sections and gost_sections[name]:
      ordered[name] = gost_sections[name]
  return ordered


def build_spec_from_assembly(assembly: dict[str, Any], products: list[dict[str, str]] | None = None) -> dict[str, Any]:
  """
  Строит спецификацию на основе дерева сборки:
  - собирает сырые позиции (designation+name+qty)
  - рассчитывает массу через calculate_mass
  - группирует одинаковые
  - разбивает по разделам
  """
  trees = assembly.get("trees") or []
  raw_items: List[SpecificationItem] = []

  def visit(node: dict[str, Any], parent_qty: float) -> None:
    designation = (node.get("designation") or "").strip()
    name = (node.get("name") or "").strip()
    description = (node.get("description") or "").strip()
    qty_here = float(node.get("qty") or 1.0)
    qty_total = parent_qty * qty_here

    # корень считаем сборкой → не добавляем как строку, только дочерние
    if parent_qty > 0:
      section = determine_section(name, designation)
      mass_unit, mass_source = calculate_mass(name or designation, volume_m3=0.0, length_m=0.0)
      raw_items.append(
        SpecificationItem(
          designation=designation,
          name=name,
          description=description,
          quantity=qty_total,
          mass_unit=mass_unit,
          mass_total=mass_unit * qty_total,
          section=section,
          material=NO_DATA,
          note=mass_source,
        )
      )

    for child in node.get("children") or []:
      visit(child, qty_total)

  for root in trees:
    visit(root, parent_qty=1.0)

  grouped = group_items(raw_items)
  sections = group_by_section(grouped)

  # Fallback: если по дереву сборки ничего не нашли, строим плоскую спецификацию по PRODUCT.
  if not grouped and products:
    flat_items: List[SpecificationItem] = []
    for p in products:
      designation = (p.get("designation") or "").strip()
      name = (p.get("name") or "").strip()
      description = (p.get("description") or "").strip()
      if not designation and not name:
        continue
      section = determine_section(name, designation)
      mass_unit, mass_source = calculate_mass(name or designation, volume_m3=0.0, length_m=0.0)
      flat_items.append(
        SpecificationItem(
          designation=designation,
          name=name,
          description=description,
          quantity=1.0,
          mass_unit=mass_unit,
          mass_total=mass_unit * 1.0,
          section=section,
          material=NO_DATA,
          note=mass_source,
        )
      )
    grouped = group_items(flat_items)
    sections = group_by_section(grouped)

  total_mass = sum(it.mass_total for it in grouped)
  total_items = len(grouped)

  json_sections: Dict[str, List[dict[str, Any]]] = {}
  for sec_name, items in sections.items():
    json_sections[sec_name] = [
      {
        "designation": it.designation,
        "name": it.name,
        "description": it.description,
        "qty": it.quantity,
        "mass_unit": it.mass_unit,
        "mass_total": it.mass_total,
        "material": it.material,
        "note": it.note,
      }
      for it in items
    ]

  return {
    "sections": json_sections,
    "totals": {
      "mass_total": total_mass,
      "item_count": total_items,
    },
  }

