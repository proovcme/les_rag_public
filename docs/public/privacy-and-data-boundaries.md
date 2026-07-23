# Privacy and data boundaries

Л.Е.С. проектировался как local-first система. Публичный репозиторий не должен содержать
данные заказчиков, runtime-секреты или индексы.

## Остаётся локально

- исходные проектные документы;
- почта, договоры и вложения;
- реальные сметы, спецификации, CAD/BIM-модели;
- Qdrant collections and snapshots;
- SQLite runtime databases;
- generated Parquet, OCR, sidecars and caches;
- admin keys, JWT secrets, provider keys and local passwords.

## Может быть публичным

- код;
- архитектурные документы без private topology;
- synthetic demo data;
- redacted screenshots;
- public-safe examples of JSON reports;
- documentation that explains the product without exposing customer facts.

## Cloud boundary

The default product posture is local-first. Cloud models can improve language quality, but they
are an operator choice. Sensitive P0 data should stay local unless the operator explicitly
approves a different policy.

## Publication rule

Before public visibility, run:

```bash
make public-check
git status --short
```

Then do a manual review:

- no credentials;
- no customer filenames or stamps in screenshots;
- no real mail senders;
- no private network topology;
- no full normative corpora without publishing rights;
- no generated indexes or model caches.

The checklist lives in [../PUBLICATION_CHECKLIST.md](../PUBLICATION_CHECKLIST.md).
