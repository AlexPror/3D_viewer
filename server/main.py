import hashlib
import re
from typing import Any

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from spec_builder import build_spec_from_assembly

try:
    from step_to_glb import step_to_glb_bytes, is_server_conversion_available
except Exception:
    step_to_glb_bytes = None
    is_server_conversion_available = lambda: False


app = FastAPI(title="3d_viewer local server", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_cache: dict[str, Any] = {}


_re_x2 = re.compile(r"\\X2\\([0-9A-Fa-f]+)\\X0\\")


def _decode_step_x2(s: str) -> str:
    """Decode STEP Part21 extended encoding \\X2\\...\\X0\\ (UTF-16BE hex)."""

    def repl(m: re.Match[str]) -> str:
        hex_str = m.group(1)
        try:
            b = bytes.fromhex(hex_str)
            return b.decode("utf-16-be", errors="replace")
        except Exception:
            return m.group(0)

    return _re_x2.sub(repl, s)


def _unescape_step_string(s: str) -> str:
    # STEP uses doubled apostrophe to escape single quote inside strings.
    return s.replace("''", "'")


def _decode_text(data: bytes) -> str:
    # Most exports are UTF-8, but some can be legacy; fallback to latin-1.
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


_re_product = re.compile(
    r"PRODUCT\s*\(\s*'((?:[^']|'')*)'\s*,\s*'((?:[^']|'')*)'\s*,\s*'((?:[^']|'')*)'",
    re.IGNORECASE,
)


def parse_products(step_text: str) -> list[dict[str, str]]:
    products: list[dict[str, str]] = []
    for m in _re_product.finditer(step_text):
        designation = _decode_step_x2(_unescape_step_string(m.group(1))).strip()
        name = _decode_step_x2(_unescape_step_string(m.group(2))).strip()
        description = _decode_step_x2(_unescape_step_string(m.group(3))).strip()
        products.append(
            {
                "designation": designation,
                "name": name,
                "description": description,
            }
        )
    return products


_re_entity = re.compile(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;", re.IGNORECASE | re.DOTALL)


def _iter_entities(step_text: str) -> list[tuple[int, str, str]]:
    """Return a list of (id, entityNameUpper, argsString) for DATA section."""
    entities: list[tuple[int, str, str]] = []
    for m in _re_entity.finditer(step_text):
        entities.append((int(m.group(1)), m.group(2).upper(), m.group(3).strip()))
    return entities


def _first_strings(args: str, n: int) -> list[str]:
    """Extract first N STEP strings from args (handles doubled quotes)."""
    out: list[str] = []
    i = 0
    L = len(args)
    while i < L and len(out) < n:
        if args[i] != "'":
            i += 1
            continue
        i += 1
        buf = []
        while i < L:
            ch = args[i]
            if ch == "'":
                if i + 1 < L and args[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                i += 1
                break
            buf.append(ch)
            i += 1
        out.append(_decode_step_x2("".join(buf)))
    return out


def _last_two_refs(args: str) -> tuple[int | None, int | None]:
    refs = [int(x) for x in re.findall(r"#(\d+)", args)]
    if len(refs) < 2:
        return None, None
    return refs[-2], refs[-1]


def _last_ref(args: str) -> int | None:
    m = re.findall(r"#(\d+)", args)
    return int(m[-1]) if m else None


def build_assembly(step_text: str) -> dict[str, Any]:
    """
    Best-effort assembly extraction for STEP AP214/AP242:
    PRODUCT -> PRODUCT_DEFINITION_FORMATION -> PRODUCT_DEFINITION
    NEXT_ASSEMBLY_USAGE_OCCURRENCE links parent/child PRODUCT_DEFINITION.
    """
    entities = _iter_entities(step_text)

    product_by_id: dict[int, dict[str, str]] = {}
    pdf_to_product: dict[int, int] = {}
    pd_to_pdf: dict[int, int] = {}
    nauo_edges: list[tuple[int, int]] = []

    for ent_id, ent, args in entities:
        if ent == "PRODUCT":
            s = _first_strings(args, 3)
            designation = _unescape_step_string(s[0] if len(s) > 0 else "").strip()
            name = _unescape_step_string(s[1] if len(s) > 1 else "").strip()
            description = _unescape_step_string(s[2] if len(s) > 2 else "").strip()
            product_by_id[ent_id] = {
                "designation": designation,
                "name": name,
                "description": description,
            }
        elif ent == "PRODUCT_DEFINITION_FORMATION":
            prod_id = _last_ref(args)
            if prod_id is not None:
                pdf_to_product[ent_id] = prod_id
        elif ent == "PRODUCT_DEFINITION":
            pdf_id = _last_ref(args)
            if pdf_id is not None:
                pd_to_pdf[ent_id] = pdf_id
        elif ent == "NEXT_ASSEMBLY_USAGE_OCCURRENCE":
            parent_pd, child_pd = _last_two_refs(args)
            if parent_pd is not None and child_pd is not None:
                nauo_edges.append((parent_pd, child_pd))

    def pd_to_product(pd_id: int) -> dict[str, str] | None:
        pdf_id = pd_to_pdf.get(pd_id)
        if pdf_id is None:
            return None
        prod_id = pdf_to_product.get(pdf_id)
        if prod_id is None:
            return None
        return product_by_id.get(prod_id)

    # Build occurrence edges on product level
    prod_edges: list[tuple[str, str]] = []
    prod_nodes: dict[str, dict[str, str]] = {}
    for p_pd, c_pd in nauo_edges:
        p = pd_to_product(p_pd)
        c = pd_to_product(c_pd)
        if not p or not c:
            continue
        p_key = f"{p.get('designation','')}|{p.get('name','')}"
        c_key = f"{c.get('designation','')}|{c.get('name','')}"
        prod_nodes[p_key] = p
        prod_nodes[c_key] = c
        prod_edges.append((p_key, c_key))

    children: dict[str, list[str]] = {}
    indeg: dict[str, int] = {k: 0 for k in prod_nodes}
    for a, b in prod_edges:
        children.setdefault(a, []).append(b)
        indeg[b] = indeg.get(b, 0) + 1
        indeg.setdefault(a, indeg.get(a, 0))

    roots = [k for k, d in indeg.items() if d == 0] or list(prod_nodes.keys())[:1]

    def build_tree(node: str, depth: int = 0) -> dict[str, Any]:
        info = prod_nodes.get(node, {"designation": "", "name": "", "description": ""})
        ch = children.get(node, [])
        # aggregate counts per direct child
        cnt: dict[str, int] = {}
        for c in ch:
            cnt[c] = cnt.get(c, 0) + 1
        return {
            "key": node,
            "designation": info.get("designation", ""),
            "name": info.get("name", ""),
            "description": info.get("description", ""),
            "children": [
                {**build_tree(c, depth + 1), "qty": cnt.get(c, 1)} for c in sorted(cnt.keys())
            ],
        }

    trees = [build_tree(r) for r in roots]
    return {
        "roots": roots,
        "trees": trees,
        "edge_count": len(prod_edges),
        "node_count": len(prod_nodes),
    }


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/step/metadata")
async def step_metadata(file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    digest = hashlib.sha1(data).hexdigest()
    if digest in _cache:
        return _cache[digest]

    text = _decode_text(data)
    products = parse_products(text)
    assembly = build_assembly(text)
    spec = build_spec_from_assembly(assembly, products)

    # De-dup by (designation, name, description) while preserving order.
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, str]] = []
    for p in products:
        key = (p["designation"], p["name"], p["description"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    res = {
        "filename": file.filename,
        "sha1": digest,
        "product_count": len(products),
        "unique_product_count": len(unique),
        "products": unique,
        "assembly": assembly,
        "spec": spec,
    }
    _cache[digest] = res
    return res


# Лимит размера STEP для серверной конвертации (байты), 100 МБ
STEP_TO_GLB_MAX_BYTES = 100 * 1024 * 1024


@app.get("/api/convert/step-to-glb/status")
def convert_step_to_glb_status() -> dict[str, Any]:
    """Проверка: доступна ли серверная конвертация STEP → GLB."""
    return {
        "available": is_server_conversion_available(),
        "max_file_bytes": STEP_TO_GLB_MAX_BYTES,
    }


@app.post("/api/convert/step-to-glb")
async def convert_step_to_glb(file: UploadFile = File(...)) -> Response:
    """
    Конвертация STEP/STP в GLB на сервере (для больших файлов).
    Возвращает бинарный GLB или 501/413/500.
    """
    if step_to_glb_bytes is None or not is_server_conversion_available():
        return Response(
            content=b"Server conversion not available (install cadquery and trimesh)",
            status_code=501,
            media_type="text/plain",
        )
    data = await file.read()
    if len(data) > STEP_TO_GLB_MAX_BYTES:
        return Response(
            content=f"File too large (max {STEP_TO_GLB_MAX_BYTES // (1024*1024)} MB)".encode(),
            status_code=413,
            media_type="text/plain",
        )
    glb_bytes = step_to_glb_bytes(data)
    if glb_bytes is None:
        return Response(
            content=b"Conversion failed",
            status_code=500,
            media_type="text/plain",
        )
    return Response(content=glb_bytes, media_type="model/gltf-binary")

