"""
Серверная конвертация STEP → GLB (для больших файлов).
Требует: cadquery, trimesh. Если недоступны — конвертация через сервер отключена.
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

_converter_available: Optional[bool] = None


def _check_deps() -> bool:
    global _converter_available
    if _converter_available is not None:
        return _converter_available
    try:
        import cadquery as cq  # noqa: F401
        import trimesh  # noqa: F401
        _converter_available = True
    except Exception:
        _converter_available = False
    return _converter_available


def step_to_glb_bytes(step_content: bytes) -> Optional[bytes]:
    """
    Конвертирует STEP (байты) в GLB (байты).
    Возвращает None, если конвертер недоступен или произошла ошибка.
    """
    if not _check_deps():
        return None
    import cadquery as cq
    import trimesh

    step_path: Optional[str] = None
    stl_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".stp", delete=False) as f:
            f.write(step_content)
            step_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
            stl_path = f.name

        importer = getattr(cq.importers, "importStep", getattr(cq.importers, "import_step", None))
        if importer is None:
            return None
        shape = importer(step_path)
        if shape is None:
            return None
        exported = False
        try:
            if hasattr(shape, "export"):
                shape.export(stl_path)
                exported = True
        except Exception:
            pass
        if not exported and getattr(cq, "exporters", None):
            try:
                cq.exporters.export(shape, stl_path)
                exported = True
            except Exception:
                pass
        if not exported and hasattr(shape, "val") and shape.val() is not None:
            try:
                shape.val().exportStl(stl_path, 0.5)
                exported = True
            except Exception:
                pass
        if not exported:
            return None

        mesh = trimesh.load(stl_path, force="mesh")
        if mesh is None:
            return None
        out = mesh.export(file_type="glb")
        return out if isinstance(out, bytes) else None
    except Exception:
        return None
    finally:
        if step_path and os.path.isfile(step_path):
            try:
                os.unlink(step_path)
            except Exception:
                pass
        if stl_path and os.path.isfile(stl_path):
            try:
                os.unlink(stl_path)
            except Exception:
                pass


def is_server_conversion_available() -> bool:
    return _check_deps()
