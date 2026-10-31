# MERN setup and verification

## Requirements

- Node.js 20.19+ or 22.12+ and npm.
- MongoDB Community Server 7+ on this computer, or an Atlas URI.
- MongoDB must support transactions. A local standalone `mongod` does not; configure a replica set before issuing or returning books.

The old Flask files and `library.db` remain in place. A pre-change backup was created at `..\Pustakalaya_Library_Management_System_backup_before_MERN_20261029_193925` (the virtual environment and Python cache were excluded; the original folder was not modified).

## Local MongoDB setup (Windows)

1. Open the MongoDB config file for the installed version as Administrator, typically:

   `C:\Program Files\MongoDB\Server\9.0\bin\mongod.cfg`

2. Add these lines at the end of the file, preserving YAML indentation:

   ```yaml
   replication:
     replSetName: rs0
   ```

3. In an Administrator PowerShell window restart the existing MongoDB Windows service:

   ```powershell
   Restart-Service MongoDB
   ```

4. From the project folder initialize the replica set once:

   ```powershell
   npm run mongo:init-replica --workspace server
   ```

   This requires the default local MongoDB listener on `127.0.0.1:27017` without access control. If your server uses authentication or a different address, set `MONGODB_ADMIN_URI` for this command to a direct connection URI for an authorized database administrator.

## Configure and run

Copy the example environment file and generate a local session secret:

```powershell
Copy-Item .env.example .env
$secret = node -p "require('crypto').randomBytes(48).toString('base64url')"
(Get-Content .env) -replace '^SESSION_SECRET=.*$', "SESSION_SECRET=$secret" | Set-Content .env
```

Check `MONGODB_URI` in `.env`; the local default is:

```text
mongodb://127.0.0.1:27017/pustakalaya?replicaSet=rs0
```

Then install and run:

```powershell
npm install
npm run create-admin --workspace server
npm run dev
```

The setup command asks for the librarian name, username, and email, creates a cryptographically random one-time password, and displays it once. Save it securely. Sign in at the Vite address printed by the command (normally `http://localhost:5173`) and use **Account** to change the password. There is no default admin or committed credential.

Production build and server commands:

```powershell
npm run build
npm start
```

Set `NODE_ENV=production` and serve the app over HTTPS before using it outside localhost; the session cookie is marked `Secure` in production.

## Optional SQLite migration

The existing database contains the original users, books, transactions, and notifications. Back up `library.db` first. The migration is one-time and refuses to write into a non-empty MongoDB database:

```powershell
npm run migrate:sqlite --workspace server
```

The migration command defaults to the project-root `library.db`. To choose another source path, pass a path relative to the project root after `--source`.

Choose either migration **or** first-admin creation for a new empty database. Migration retains student password hashes (Werkzeug scrypt hashes can still be checked after import), preserves records and stock, and rotates any legacy librarian password to a new random one-time password printed by the command. Change that password at **Account** immediately after signing in. The SQLite source file is read-only to the migration.

## Tests

Run the business-rule tests without a database:

```powershell
npm test
```

The integration test requires a dedicated, disposable local MongoDB database named `pustakalaya_test` and an `MONGODB_URI` that connects to it through a replica set. It drops that test database before running; **never point it at production or the library database**. The pre-conversion Flask tests remain in `tests\` and can be run with the original `.venv`.

## Demonstrate overdue fines

New loans still default to 14 days, and fines remain ₹2 per overdue day. To demonstrate the workflow without waiting, sign in as a librarian, issue a book to a test member, then use the date calendar in **Issue / return → Currently issued books** to set that active loan's due date to yesterday. This administrative override applies to any active loan; changing a real member's due date changes their loan terms. The accruing fine appears in Fine management and in the member's loan view. Record the book's return to finalize the fine, then use **Fine management → Mark paid** to record collection. Payment recording is librarian-only; the application does not process online payments.

## Application structure

- `client\src\` — React pages, reusable components, styles, and API client.
- `server\src\models\` — Mongoose models for users, books, transactions, and notifications.
- `server\src\routes\api.js` — REST endpoints, authentication, and authorization.
- `server\src\services\loanService.js` — transactional borrowing, return, title-limit, and fine rules.
- `server\scripts\createAdmin.js` — secure one-time librarian creation.
- `server\scripts\migrateSqlite.js` — read-only SQLite to MongoDB migration.
- `.env.example` — configuration template; keep `.env` private.

## Requirements verification checklist

Verification completed:

- [x] Visitor catalogue search/filter and book availability; the React catalogue was opened in a browser against the test API.
- [x] Librarian sign-in and dashboard; browser smoke test also created a member, issued a book, and recorded its return.
- [x] Registration, username/email login, logout, member-only loan/fine history, and notifications (API integration tests).
- [x] Librarian-only book/member management, issue/return, fine collection, reminders, reports, and CSV endpoints (API integration tests).
- [x] Librarian-only due-date calendar for active loans; past due dates show accruing fines to librarians and members, and returned fines can be collected by the librarian.
- [x] 14-day loan, ₹2 per overdue day, 3 active books, and duplicate active-title restriction.
- [x] Overdue and unpaid-fine borrowing restrictions.
- [x] Atomic stock updates and protection against duplicate/concurrent issue and return.
- [x] Books, members, issued, returned, fines, and transaction-history CSV exports.
- [x] SQLite migration imported 2 users and 7 books into a disposable MongoDB database (the source had 0 transactions and 0 notifications); source database hash remained unchanged.
- [x] Frontend production build, all 7 MERN tests (including MongoDB integration), all 30 original Flask tests, and JavaScript syntax checks passed.
- [x] Server-side validation, CSRF protection, session authentication, and password hashing (automated tests).
- [ ] Responsive layouts were not separately visually checked at multiple viewport sizes.

Barcode/QR, reservations/renewals, external email/SMS, e-books, mobile apps, multi-branch support, and public internet hosting remain outside scope as documented in the report.
