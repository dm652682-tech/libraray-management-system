# Pustakalaya Library Management System

The current implementation is a MERN application: React, Express, Node.js, and MongoDB. The original Flask/SQLite application and its tests are preserved in this folder for reference and data migration.

## Windows quick start

1. Install Node.js 20.19+ (or 22.12+) and MongoDB Community Server 7 or newer.
2. Configure MongoDB as a single-node replica set. MongoDB transactions are required to keep issue/return records and stock updates consistent. See [MongoDB setup](#mongodb-setup).
3. Copy `.env.example` to `.env`. Set a random `SESSION_SECRET` (at least 32 characters) and confirm `MONGODB_URI` points to your local `rs0` replica set.
4. From PowerShell in this folder, run:

   ```powershell
   npm install
   npm run create-admin --workspace server
   npm run dev
   ```

5. Save the one-time librarian password printed by the setup command. Open the Vite URL shown in the terminal (normally http://localhost:5173) and change that password under **Account** after signing in.

For detailed setup, migration, test commands, API structure, and the requirement checklist, see [MERN_SETUP.md](./MERN_SETUP.md).

## Original application

The prior Flask app remains available as `app.py` with its templates, styles, tests, and `library.db`. Run it separately with the existing Windows `run.bat`; it is not used by the MERN application. The SQLite database is never modified by the migration tool.
