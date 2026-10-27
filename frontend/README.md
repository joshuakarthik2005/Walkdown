# Walkdown front end

Next.js (App Router, TypeScript). It shows the agent's work and results; the product logic lives in the FastAPI back end.

```
cd frontend
copy .env.example .env.local   # NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev                    # http://localhost:3000
```

Start the API first: `.venv\Scripts\python.exe -m uvicorn backend.api.app:app --port 8000`.
