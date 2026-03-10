# Local server for 3d_viewer

## Run

Рекомендуется использовать виртуальное окружение, чтобы не конфликтовать с глобальным Python (numpy, cadquery и др.).

```powershell
cd C:\3d_viewer\server
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Health check: `http://localhost:8000/api/health`

## API

### POST `/api/step/metadata`

Multipart form-data:
- `file`: STEP `.stp/.step`

Returns JSON with extracted `PRODUCT('designation','name','description',...)` strings.
Supports decoding STEP `\X2\...\X0\` (UTF-16BE hex) and `''` escaping.

### GET `/api/convert/step-to-glb/status`

Returns `{ "available": true|false, "max_file_bytes": N }`.  
`available` — true, если установлены `cadquery` и `trimesh` (серверная конвертация STEP→GLB включена).

### POST `/api/convert/step-to-glb`

Multipart form-data: `file` — STEP (`.stp`/`.step`).  
Конвертирует STEP в GLB на сервере; возвращает бинарный GLB (`model/gltf-binary`) или 501/413/500.  
Лимит размера файла: 100 МБ. Вьюер сначала пробует этот endpoint для STEP; при недоступности или ошибке используется конвертация в браузере (WASM).

