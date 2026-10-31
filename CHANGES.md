# Changes in this update (report alignment)
- Student dashboard redesigned: 4 cards, overdue label, loan rule footer.
- New `/my-books` page ("My books & fines"); student menu renamed (Search books / My books & fines / Notifications).
- Notifications empty-state text updated.
- `run.bat` / `run.sh` one-click start; `HOST`/`PORT` env vars for LAN demo.
- `FINE_PER_DAY` configurable by environment variable (default unchanged at 10).
- `Procfile`, `render.yaml`, gunicorn added for hosting.
- tests/test_borrowing.py: 3 new tests (30 total).

# Changes in this update
- app.py: planned return date (tomorrow .. +14 days) required and validated server-side on /borrow; shared create_loan() used by student borrow and librarian issue (one write transaction, atomic stock decrement); atomic return (stock added once); catalogue search now includes category and treats % and _ literally; deletion blocked while unpaid fines exist; return redirects only to same-site referrers; FLASK_DEBUG controls debug mode (default off); MAX_BOOKS and date window exposed to templates.
- templates/catalogue.html: ID column, date picker + Borrow form for students, search placeholder.
- templates/issue.html: uses MAX_BOOKS instead of a hard-coded 3.
- static/style.css: .borrow-form and .sr-only rules appended (theme untouched).
- tests/test_borrowing.py: 22 new tests. README.md updated.
