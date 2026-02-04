# PTDS Frontend (React + TS, VSCode-style)

## 1) Run
```bash
npm install
npm run dev
```

## 2) Backend proxy
Vite 已配置把 `/api` 代理到 `http://localhost:8000`（FastAPI）。

## 3) Features mapped
- Explorer: `/api/v1/folders/tree` and open Files tab (uses `/api/v1/files`)
- Search: `/api/v1/files?q=...`
- Chat: POST + SSE `/api/v1/chat/sessions/{id}/messages` (fetch streaming)
- KG: `/api/v1/kg/subgraph`
- Markdown: `/api/v1/md/{doc_id}`, `/api/v1/md/{doc_id}/patch`
- Assets: `/api/v1/assets` and open Asset tab

> 当前是可运行骨架：后端若返回空数据，界面依旧可跑通。
