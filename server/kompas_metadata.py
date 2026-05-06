from __future__ import annotations

import logging
import os
import re
import uuid
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


log = logging.getLogger("kompas_metadata")


try:
    import pythoncom  # type: ignore
except Exception:  # pragma: no cover
    pythoncom = None


def _com_available() -> bool:
    try:
        import win32com.client  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def _to_float_color_component(v: Any) -> float:
    try:
        x = float(v)
    except Exception:
        return 0.7
    if x > 1.0:
        x = x / 255.0
    return max(0.0, min(1.0, x))


def _rgb_to_hex(r: Any, g: Any, b: Any) -> str:
    rr = int(round(_to_float_color_component(r) * 255.0))
    gg = int(round(_to_float_color_component(g) * 255.0))
    bb = int(round(_to_float_color_component(b) * 255.0))
    return f"#{rr:02x}{gg:02x}{bb:02x}"


def _extract_qty_from_name(name: str) -> tuple[str, int]:
    s = (name or "").strip()
    if not s:
        return "", 1
    m = re.search(r"\s*\((\d+)\)\s*$", s)
    if not m:
        return s, 1
    qty = max(1, int(m.group(1)))
    return s[: m.start()].strip(), qty


def _com_get_first_str(obj: Any, attr_names: tuple[str, ...]) -> str:
    for attr in attr_names:
        try:
            if not hasattr(obj, attr):
                continue
            raw = getattr(obj, attr)
            if callable(raw):
                raw = raw()
            if raw is None:
                continue
            val = str(raw).strip()
            if val:
                return val
        except Exception:
            continue
    return ""


def _get_part_source_path(part: Any) -> str:
    path = _com_get_first_str(
        part,
        (
            "FileName",
            "fileName",
            "FullFileName",
            "fullFileName",
            "PathName",
            "pathName",
            "SrcFileName",
            "srcFileName",
        ),
    )
    if path:
        return path
    for doc_attr in ("Document", "document", "PartDocument", "partDocument"):
        try:
            doc = getattr(part, doc_attr, None)
            if not doc:
                continue
            inner = _com_get_first_str(
                doc, ("FileName", "fileName", "FullName", "fullName", "PathName", "pathName")
            )
            if inner:
                return inner
        except Exception:
            continue
    return ""


def _get_part_marking(part: Any) -> str:
    return _com_get_first_str(
        part,
        (
            "Marking",
            "marking",
            "Designation",
            "designation",
            "ArticleDesignation",
            "articleDesignation",
            "ReferenceDesignation",
            "referenceDesignation",
            "StampDesignation",
            "stampDesignation",
            "Article",
            "article",
            "PartNumber",
            "partNumber",
        ),
    )


def _get_part_display_name(part: Any) -> str:
    name = _com_get_first_str(part, ("Name", "name", "DetailName", "detailName", "PartName", "partName"))
    return name or "Без имени"


def _is_suppressed_or_excluded(part: Any) -> bool:
    for attr in (
        "Suppressed",
        "IsSuppressed",
        "Excluded",
        "IsExcluded",
        "ExcludedFromSpecification",
        "ExcludeFromSpecification",
    ):
        try:
            value = getattr(part, attr, None)
            if callable(value):
                value = value()
            if isinstance(value, bool) and value:
                return True
            if isinstance(value, (int, float)) and int(value) != 0:
                return True
        except Exception:
            continue
    return False


def _safe_doc_kind(path: str) -> str:
    p = (path or "").lower()
    if p.endswith(".a3d"):
        return "assembly"
    if p.endswith(".m3d"):
        return "part"
    return "unknown"


def _safe_color_from_part(part: Any) -> str:
    for color_obj_attr in ("Color", "color", "MaterialColor", "materialColor"):
        try:
            c = getattr(part, color_obj_attr, None)
            if callable(c):
                c = c()
            if not c:
                continue
            r = getattr(c, "Red", None)
            g = getattr(c, "Green", None)
            b = getattr(c, "Blue", None)
            if r is not None and g is not None and b is not None:
                return _rgb_to_hex(r, g, b)
        except Exception:
            continue
    return "#8ea3b5"


@dataclass
class _Node:
    node_id: str
    part_id: str
    instance_id: str
    name: str
    designation: str
    qty: int
    source_path: str
    kind: str
    children: list["_Node"]


class KompasConnector:
    def __init__(self) -> None:
        self.api7: Any = None
        self.app: Any = None
        self.connected = False

    def connect(self) -> bool:
        if not _com_available():
            return False
        try:
            if pythoncom is not None:
                pythoncom.CoInitialize()
            from win32com.client import Dispatch  # type: ignore

            self.api7 = Dispatch("Kompas.Application.7")
            self.app = self.api7
            self.app.Visible = True
            self.connected = True
            return True
        except Exception as exc:
            log.exception("Kompas connect failed: %s", exc)
            self.connected = False
            return False

    def disconnect(self) -> None:
        self.api7 = None
        self.app = None
        self.connected = False
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def open_document(self, path: str) -> bool:
        if not self.connected and not self.connect():
            return False
        try:
            abs_path = str(Path(path).expanduser().resolve())
            doc = self.app.Documents.Open(abs_path, False)
            return bool(doc)
        except Exception as exc:
            log.exception("Open document failed: %s", exc)
            return False

    def get_top_part(self) -> Any:
        if not self.api7:
            return None
        for doc_attr in ("ActiveDocument3D", "ActiveDocument"):
            try:
                doc = getattr(self.api7, doc_attr, None)
                if not doc:
                    continue
                top = getattr(doc, "TopPart", None)
                if top:
                    return top
            except Exception:
                continue
        return None


def _get_children_parts(i_part_asm: Any) -> list[Any]:
    result: list[Any] = []
    i_part_asm = i_part_asm

    get_part = getattr(i_part_asm, "GetPart", None)
    if callable(get_part):
        for i in range(10000):
            try:
                part = get_part(i)
            except Exception:
                break
            if not part:
                break
            result.append(part)
        if result:
            return result

    parts_coll = getattr(i_part_asm, "Parts", None) or getattr(i_part_asm, "GetParts", None)
    if parts_coll is not None:
        try:
            cnt = getattr(parts_coll, "Count", None)
            if callable(cnt):
                cnt = cnt()
            if cnt is None:
                get_count = getattr(parts_coll, "GetCount", None)
                cnt = get_count() if callable(get_count) else 0
            for i in range(int(cnt or 0)):
                item = parts_coll.Item(i) if hasattr(parts_coll, "Item") else None
                if item:
                    result.append(item)
        except Exception:
            pass
    return result


def _visit_tree(
    parent_part: Any,
    model_key: str,
    parent_node_id: str | None,
    node_acc: list[dict[str, Any]],
    part_index: dict[str, dict[str, Any]],
    instance_acc: list[dict[str, Any]],
    mesh_bindings: list[dict[str, Any]],
) -> list[_Node]:
    out: list[_Node] = []
    for part in _get_children_parts(parent_part):
        if _is_suppressed_or_excluded(part):
            continue

        source_path = _get_part_source_path(part)
        designation = (_get_part_marking(part) or "").strip()
        raw_name = _get_part_display_name(part)
        name, qty = _extract_qty_from_name(raw_name)
        kind = _safe_doc_kind(source_path)
        color = _safe_color_from_part(part)

        key_source = source_path.strip().lower() if source_path else ""
        part_key = f"{designation}|{name}|{key_source}|{kind}"
        if part_key not in part_index:
            part_id = f"part_{len(part_index) + 1}"
            part_index[part_key] = {
                "id": part_id,
                "name": name or "Без имени",
                "designation": designation,
                "sourcePath": source_path,
                "kind": kind,
                "color": color,
            }
        part_id = part_index[part_key]["id"]

        instance_id = f"inst_{uuid.uuid4().hex[:12]}"
        node_id = f"node_{uuid.uuid4().hex[:10]}"

        instance_acc.append(
            {
                "id": instance_id,
                "partId": part_id,
                "parentNodeId": parent_node_id,
                "qty": qty,
                "modelKey": model_key,
            }
        )

        mesh_bindings.append(
            {
                "instanceId": instance_id,
                "partId": part_id,
                "meshNameHint": Path(source_path).stem if source_path else name,
            }
        )

        node = _Node(
            node_id=node_id,
            part_id=part_id,
            instance_id=instance_id,
            name=name or "Без имени",
            designation=designation,
            qty=qty,
            source_path=source_path,
            kind=kind,
            children=[],
        )

        child_nodes: list[_Node] = []
        if kind == "assembly":
            child_nodes = _visit_tree(
                part,
                model_key=model_key,
                parent_node_id=node_id,
                node_acc=node_acc,
                part_index=part_index,
                instance_acc=instance_acc,
                mesh_bindings=mesh_bindings,
            )
            node.children = child_nodes

        node_acc.append(
            {
                "id": node_id,
                "partId": part_id,
                "instanceId": instance_id,
                "parentId": parent_node_id,
                "name": node.name,
                "designation": node.designation,
                "qty": node.qty,
                "kind": node.kind,
                "sourcePath": node.source_path,
                "children": [ch.node_id for ch in child_nodes],
            }
        )
        out.append(node)
    return out


def read_kompas_metadata(assembly_path: str) -> dict[str, Any]:
    asm_abs = str(Path(assembly_path).expanduser().resolve())
    if not os.path.isfile(asm_abs):
        raise FileNotFoundError(f"Assembly not found: {asm_abs}")

    connector = KompasConnector()
    if not connector.connect():
        raise RuntimeError("Не удалось подключиться к КОМПАС-3D COM")
    try:
        if not connector.open_document(asm_abs):
            raise RuntimeError("Не удалось открыть файл сборки в КОМПАС")

        top_part = connector.get_top_part()
        if not top_part:
            raise RuntimeError("Не удалось получить TopPart активной сборки")

        assembly_name = _com_get_first_str(top_part, ("Name", "name")) or Path(asm_abs).stem
        assembly_designation = (_get_part_marking(top_part) or "").strip()
        model_key = Path(asm_abs).name

        node_acc: list[dict[str, Any]] = []
        part_index: dict[str, dict[str, Any]] = {}
        instance_acc: list[dict[str, Any]] = []
        mesh_bindings: list[dict[str, Any]] = []

        roots = _visit_tree(
            top_part,
            model_key=model_key,
            parent_node_id=None,
            node_acc=node_acc,
            part_index=part_index,
            instance_acc=instance_acc,
            mesh_bindings=mesh_bindings,
        )

        parts = list(part_index.values())

        qty_by_part: dict[str, int] = {}
        for inst in instance_acc:
            part_id = inst["partId"]
            qty_by_part[part_id] = qty_by_part.get(part_id, 0) + int(inst.get("qty", 1))

        bom: list[dict[str, Any]] = []
        for p in parts:
            pid = p["id"]
            bom.append(
                {
                    "partId": pid,
                    "designation": p.get("designation", ""),
                    "name": p.get("name", ""),
                    "qty": qty_by_part.get(pid, 0),
                    "material": "нет данных",
                }
            )
        bom.sort(key=lambda x: (x["designation"], x["name"]))

        return {
            "source": {
                "assemblyPath": asm_abs,
                "assemblyName": assembly_name,
                "assemblyDesignation": assembly_designation,
            },
            "parts": parts,
            "instances": instance_acc,
            "meshBindings": mesh_bindings,
            "tree": {
                "nodes": node_acc,
                "roots": [n.node_id for n in roots],
            },
            "bom": bom,
        }
    finally:
        connector.disconnect()


def build_assembly_map(assembly_path: str) -> dict[str, Any]:
    """
    Нормализованный контракт для матчинга mesh-кластеров:
    - stable parts/instances
    - signatures (file/name/designation) для дальнейшего сопоставления геометрии.
    """
    meta = read_kompas_metadata(assembly_path)
    source = meta.get("source", {})
    parts = meta.get("parts", [])
    instances = meta.get("instances", [])
    tree = meta.get("tree", {})
    bom = meta.get("bom", [])

    part_signatures: list[dict[str, Any]] = []
    for p in parts:
        source_path = str(p.get("sourcePath", "") or "")
        name = str(p.get("name", "") or "")
        designation = str(p.get("designation", "") or "")
        file_ext = Path(source_path).suffix.lower() if source_path else ""
        file_name = Path(source_path).name if source_path else ""
        file_size = None
        file_mtime = None
        if source_path and os.path.isfile(source_path):
            try:
                st = os.stat(source_path)
                file_size = int(st.st_size)
                file_mtime = float(st.st_mtime)
            except Exception:
                pass
        fingerprint_src = "|".join(
            [
                str(file_name).lower(),
                str(file_size if file_size is not None else ""),
                str(designation).strip().lower(),
                str(name).strip().lower(),
            ]
        )
        fingerprint = hashlib.sha1(fingerprint_src.encode("utf-8", errors="ignore")).hexdigest()
        part_signatures.append(
            {
                "partId": p.get("id"),
                "sourcePath": source_path,
                "fileName": file_name,
                "fileExt": file_ext,
                "fileSize": file_size,
                "fileMtime": file_mtime,
                "nameNorm": name.strip().lower(),
                "designationNorm": designation.strip().lower(),
                "fingerprint": fingerprint,
            }
        )

    return {
        "version": 1,
        "source": source,
        "parts": parts,
        "instances": instances,
        "tree": tree,
        "bom": bom,
        "signatures": {
            "partSignatures": part_signatures,
        },
        "matchingHints": {
            "primaryKeys": ["partId", "instanceId"],
            "fallbackKeys": ["sourcePath", "designationNorm", "nameNorm", "fingerprint"],
            "geometryKeysPlanned": ["bbox", "volume", "surfaceArea"],
        },
    }

