# API Envelope (Copy/Paste Reference)

## Success

```json
{ "ok": true, "request_id": "uuid", "data": {} }
```

## Error

```json
{
  "ok": false,
  "request_id": "uuid",
  "error": { "code": "...", "message": "...", "details": {} }
}
```

## Diagnostics

```json
{
  "ok": true,
  "request_id": "uuid",
  "data": {},
  "diagnostics": [{ "code": "...", "message": "...", "details": {} }]
}
```
