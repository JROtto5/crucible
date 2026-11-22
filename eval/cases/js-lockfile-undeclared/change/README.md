# notes-server

A small notes API.

    cd server && npm ci && npm start

Set `NOTES_JWT_SECRET` and `NOTES_ADMIN_PASSWORD`, then `POST /login` for a token.
Uploads go to `server/data/uploads` (5 MB max).
