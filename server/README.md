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

### Auth + collaboration (этап 1 — каркас; состав проекта; связки PDF↔3D)

Локальная SQLite БД создается автоматически: `server/collab.sqlite3`  
Путь можно переопределить переменной `COLLAB_DB_PATH`.

Доп. переменные:
- `COLLAB_AUTH_SECRET` — секрет подписи токена (обязательно сменить в проде)
- `COLLAB_TOKEN_TTL_SECONDS` — TTL токена (по умолчанию 43200)
- `YANDEX_TELEMOST_OAUTH` — OAuth-токен для [API Яндекс Телемоста](https://yandex.ru/dev/telemost/doc/) (создание комнаты по запросу `GET /api/projects/{id}/telemost`; без токена вкладка Телемоста показывает подсказку администратору)

Endpoints:
- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/me`
- `GET /api/projects`
- `POST /api/projects`
- `POST /api/projects/{project_id}/members`
- `GET /api/projects/{project_id}/members` — участники с ролями и имя/email
- `PATCH /api/projects/{project_id}/members/{user_id}` — смена роли (как у приглашения; роль «ГИП» задаёт только ГИП)
- `DELETE /api/projects/{project_id}/members/{user_id}` — выход из проекта (себя) или исключение участника; нельзя исключить/уйти, оставив проект без ГИПа при одном ГИПе
- `GET /api/projects/{project_id}/telemost` — ссылка для входа в звонок Телемоста по проекту (одна комната на проект; первое обращение создаёт конференцию через API Яндекс при наличии `YANDEX_TELEMOST_OAUTH`)
- `GET /api/projects/{project_id}/attachments` — список вложений чата проекта (метаданные)
- `GET /api/projects/{project_id}/asset-pairs` — реестр связок PDF ↔ 3D по проекту
- `GET /api/projects/{project_id}/asset-pairs/suggestions` — кандидаты на связку (одинаковое имя без расширения у PDF и модели в вложениях)
- `POST /api/projects/{project_id}/asset-pairs` — добавить связку (вложения чата и/или только имена `pdfStem` / `modelStem`)
- `DELETE /api/projects/{project_id}/asset-pairs/{pair_id}`
- `GET /api/projects/{project_id}/channels`
- `POST /api/projects/{project_id}/channels`
- `GET /api/projects/{project_id}/channels/{channel_id}/messages`
- `POST /api/projects/{project_id}/channels/{channel_id}/messages`
- `POST /api/projects/{project_id}/channels/{channel_id}/read`
- `POST /api/projects/{project_id}/attachments/upload`
- `GET /api/projects/{project_id}/attachments/{attachment_id}`
- `WS /api/projects/{project_id}/ws?token=<bearer-token>` — после `ws.connected` сервер шлёт цепочку `yjs.sync` (история CRDT для совместных заметок); клиенты шлют `yjs.update` и `yjs.awareness` (курсоры), сервер ретранслирует участникам проекта

Для защищенных endpoint используйте:
`Authorization: Bearer <token>`

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

