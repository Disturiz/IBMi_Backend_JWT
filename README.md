
# Backend — JWT + Autocomplete (Schemas & Tables)

Endpoints:
- `POST /login` → Bearer token (expira en `JWT_EXPIRE_MIN`)
- `POST /extract?format=json|csv|xlsx` → requiere `Authorization: Bearer <token>` y body: `{"library","table","limit"}`
- `POST /catalog` → sugiere tablas por `library` y `pattern`
- `POST /catalog/schemas` → sugiere librerías (schemas) por `pattern`
- `GET /health`

## Variables de entorno
- `JT400_JAR` (obligatoria para consultas reales)
- `JWT_SECRET` (cámbiala en producción)
- `JWT_EXPIRE_MIN` (TTL del token, 5 recomendado)
- `ALLOW_LIBS` (lista blanca de librerías, opcional pero recomendable)

## Desarrollo
```bash
cd backend
python -m pip install --upgrade pip
pip install -r requirements.txt
# Windows PowerShell:
#   $env:JT400_JAR="$PWD\drivers\jt400.jar"
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

## Login
```bash
curl -X POST 'http://localhost:8000/login'      -H 'content-type: application/json'      -d '{"host":"PUB400.COM","user":"USER","password":"PASS"}'
```

## Extract (JSON)
```bash
TOKEN="..."
curl -X POST 'http://localhost:8000/extract?format=json'      -H "authorization: Bearer $TOKEN" -H 'content-type: application/json'      -d '{"library":"QIWS","table":"QCUSTCDT","limit":10}'
```

## Catalog
```bash
curl -X POST 'http://localhost:8000/catalog'      -H "authorization: Bearer $TOKEN" -H 'content-type: application/json'      -d '{"library":"QIWS","pattern":"QCUST%","limit":10}'

curl -X POST 'http://localhost:8000/catalog/schemas'      -H "authorization: Bearer $TOKEN" -H 'content-type: application/json'      -d '{"pattern":"QI%","limit":10}'
```
# IBMi_Backend_JWT
