# Integrated Health Programs Data Management System

A full-stack Django application built to the "Integrated Health Programs Data
Management System" requirements: centralized activity reporting, health
screening programs (10 tools sharing one demographic core), training &
capacity building, case management/referrals, role-based dashboards, and
bulk Excel/CSV upload against the client-supplied templates.

Runs on **SQLite** out of the box for local development/testing, and
switches to **PostgreSQL** for staging/production with a single environment
variable — no code changes required.

---

## 1. Project layout

```
health_dms/
├── health_dms/          # Django project settings, root URLs, WSGI/ASGI
├── core/                 # Users, roles, geography (Region/LocalCouncil/Jamatkhana), audit log, permissions
│   ├── models.py          - Custom User model with role + geography scoping
│   ├── permissions.py     - RoleRequiredMixin, scope_queryset_by_geography()
│   ├── middleware.py       - Audit logging helper
│   ├── management/commands/seed_demo_data.py  - Demo data & demo users
│   └── tests.py
├── dashboard/            # Everything from the requirements doc
│   ├── models.py           - ActivityReport, Participant, 10 screening models,
│   │                         TrainingProgram/Attendance, CaseRecord/CaseFollowUp,
│   │                         UploadBatch
│   ├── importers.py        - Generic Excel/CSV bulk-import engine (alias-based
│   │                         header mapping straight from the supplied templates)
│   ├── views.py             - Dashboards (Overview/Activity/Screening/Training/
│   │                          Case), CRUD, CSV export, upload workflow
│   └── tests.py
├── templates/            # Bootstrap 5 + Chart.js UI
├── static/                # Custom CSS
├── requirements.txt
├── .env.example
└── manage.py
```

## 2. Role-based access model

| Role | Scope | Notes |
|---|---|---|
| **National Admin** | All regions | Full access, user management, all dashboards |
| **Regional Coordinator** | Assigned Region | Sees/enters data only for their Region |
| **Local Council Officer** | Assigned Local Council | Sees/enters data only for their Local Council |
| **Data Entry Operator** | Assigned Local Council | Can upload/enter data for their Local Council |
| **Viewer** | Region or Local Council (read-only) | Same scoping, no write access to uploads |

Scoping is enforced centrally in `core/permissions.py::scope_queryset_by_geography()`
and applied to every dashboard/list/export view — nobody outside their scope
can see, upload, or export another region's data, regardless of URL guessing.

## 3. Health screening design decision

The requirements list 10 different screening tools (Cardiac Risk Assessment,
DASS-21 Mental Health, CBE, Mammogram, Elderly Eye, Adolescent Health,
HbA1c, Nutrition, Elderly Neurological/ICOPE, Adult/Camp Screening), each with
its own long, mostly-unique set of assessment columns, on top of a **shared
demographic core** (captured once per participant).

Rather than hand-building ten 25+ column tables, every screening model:

1. Shares one `Participant` record (created once, reused across all
   screenings for that person — exactly as required: *"demographic
   information entered once … automatically populate the following screening
   forms"*).
2. Inherits common outcome fields (`screening_date`, `referred`,
   `risk_category`, `reason_for_referral`, `remarks`) from `ScreeningRecordBase`.
3. Stores its remaining, tool-specific columns in a `details` JSONField keyed
   **exactly** to that tool's Excel template headers — nothing from the
   source spreadsheet is ever dropped, and the field is still fully
   queryable/filterable in Postgres or SQLite.

This keeps the schema maintainable while remaining 100% aligned with the
supplied Excel templates.

## 4. Bulk Excel/CSV upload

`Bulk Upload` (top nav) lets any uploader role pick a form type and upload a
`.xlsx`/`.xls`/`.csv` file matching the given template. The importer
(`dashboard/importers.py`):

- Normalizes headers (`"CNIC/NIC Number"` → `cnic_nic_number`) and maps them
  onto canonical fields via an alias table built from every template header
  supplied in the requirements doc.
- Auto-creates Region → Local Council → Jamatkhana records if they don't
  already exist.
- Processes **row-by-row inside a transaction**: a bad row is logged with its
  row number and reason, and processing continues — one bad row never fails
  the whole batch.
- Leaves an audit trail (`UploadBatch` + `AuditLog`) with success/error
  counts and a downloadable-in-browser error report.

## 5. Setup

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # edit as needed

python manage.py migrate
python manage.py seed_demo_data  # optional: sample regions/portfolios/demo users
python manage.py createsuperuser
python manage.py runserver
```

Visit `http://127.0.0.1:8000/` and log in.

### Demo users (created by `seed_demo_data`, password for all: `Passw0rd!123`)

| Username | Role |
|---|---|
| `national_admin` | National Admin |
| `regional_coord` | Regional Coordinator (Karachi) |
| `local_officer` | Local Council Officer (Karachi Central) |
| `data_entry` | Data Entry Operator (Karachi Central) |

## 6. Switching to PostgreSQL

Set these in `.env` (or your process environment) and re-run migrations —
no code changes needed:

```
DJANGO_DB_ENGINE=postgres
POSTGRES_DB=health_dms
POSTGRES_USER=health_dms
POSTGRES_PASSWORD=your-password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

```bash
python manage.py migrate
python manage.py seed_demo_data
```

## 7. Production notes

- Set `DJANGO_DEBUG=False` and a real `DJANGO_SECRET_KEY` + `DJANGO_ALLOWED_HOSTS`.
- Run `python manage.py collectstatic` (Whitenoise serves compressed,
  cache-busted static assets automatically once `DEBUG=False`).
- Run behind Gunicorn (included in requirements.txt):
  `gunicorn health_dms.wsgi:application`
- Point `MEDIA_ROOT` at persistent/object storage for uploaded photos,
  documents and Excel files if deploying to an ephemeral filesystem.

## 8. Running tests

```bash
python manage.py test core dashboard
```

52 tests cover: user/role model validation, authentication, permission
enforcement (national-only views, upload access by role), all core models,
the Excel/CSV importer (unit + end-to-end via `UploadBatch`), role-based data
scoping (regional/local users only see their own data), and case-management
workflows (case creation, follow-ups).

## 9. What's covered vs. the requirements doc

| Requirement | Implemented as |
|---|---|
| Activity Reporting Tool | `ActivityReport` model, dashboard, CRUD, CSV/PDF export |
| Health Screening Programs (10 tools, shared demographics) | `Participant` + 10 screening models sharing one demographic core |
| Training & Capacity Building + digital attendance | `TrainingProgram` + `TrainingAttendance` |
| Case Management & Referral | `CaseRecord` + `CaseFollowUp`, priority/status tracking |
| **Total Beneficiaries** | KPI card on Overview + Activity dashboards |
| **Budget Utilization** | `BudgetAllocation` model (per portfolio/region/fiscal year) vs. `cost` recorded on Activities/Trainings; shown on Overview, Activity, Training dashboards |
| **Activities conducted** | KPI + list + monthly/yearly trend |
| **Screenings types** | Per-program breakdown table + chart on Screening dashboard |
| **Referrals generated / Referral rates** | Raw counts *and* referral-rate % everywhere referrals are shown |
| **Cases under follow-up / Cases closed** | KPI cards + closure-rate % on Overview and Case dashboards |
| **Region-wise analysis** | On every dashboard, plus a combined cross-module table on Overview |
| **Portfolio-wise analysis** | On Activity/Training dashboards directly; combined Activity+Training+Screening table on Overview |
| **Program-wise analysis** | On Activity/Training dashboards; per-program breakdown on Screening dashboard |
| **Monthly and yearly trends** | Both, on every one of the 5 dashboards |
| **Age and gender analysis** | Stacked age-group/gender chart on Overview and Screening dashboards |
| **Training statistics** | Attendance-status breakdown, top trainers, avg. duration/participants, attendance rate |
| **Export charts and reports** | Real PDF export (server-rendered charts + tables via matplotlib/reportlab) *and* CSV export, on every dashboard |
| Role-based access / multi-user | Custom `User` model, 5 roles, geography-scoped queries everywhere |
| Bulk Excel/CSV import | `UploadBatch` + generic importer |
| Audit trail | `AuditLog` model + `log_action()` helper on every create/update/delete/login/import |
| Search & filter | Search boxes on activities/screenings/participants/users; **filter bar (date range, region, portfolio, program, status, priority) on every dashboard, applied identically to on-screen analytics, CSV export, and PDF export** |
| SQLite→Postgres switch | Single `DJANGO_DB_ENGINE` env var |

Items explicitly out of scope for this build (flagged as "if feasible" /
lower-priority in the requirements doc, and best handled as later
iterations): offline-first mobile data entry, KOBO API live sync, automated
follow-up push notifications/SMS reminders, and duplicate-record fuzzy
matching. The data model and audit trail are structured so these can be
added without breaking changes.

## 10. Dashboard filters & exports (how they work)

Every dashboard (Overview, Activity, Screening, Training, Case) has a filter
bar at the top:

| Dashboard | Filters available |
|---|---|
| Overview | Date range, Region, Portfolio |
| Activity Reporting | Date range, Region, Portfolio, Program |
| Screening Programs | Date range, Region, Screening Program (narrows to one of the 10 tools) |
| Training & Capacity | Date range, Region, Portfolio, Program |
| Case Management | Date range, Region, Status, Priority |

Filters are plain querystring parameters (`?date_from=2026-01-01&region=3`),
so they're shareable/bookmarkable links. The exact same `DashboardFilters`
object is used to build the on-screen charts/tables **and** the CSV/PDF
export for that dashboard — the "Export CSV" / "Export PDF" buttons carry
the current filter selection forward automatically, so what you see is what
you download.

**Budget Utilization intentionally ignores these filters** — it's a
fiscal-year figure tied to `BudgetAllocation` records, not a date-range
metric, so it always reflects the user's full role-scope regardless of the
filter bar. Everything else on every dashboard respects the active filters.

PDF exports are generated server-side (matplotlib for chart images,
reportlab for layout) — they're real downloadable PDF files, not a
browser print dialog. A "Print" button is still available on every
dashboard as a quick alternative.

## 11. Changelog — files changed since the first delivered zip

**New files (this round: filters + CSV/PDF export):**
- `dashboard/filters.py` — shared filter parsing (`DashboardFilters`) + choice-list helpers
- `dashboard/reporting.py` — PDF report builder (matplotlib chart images + reportlab layout)
- `templates/dashboard/_filter_overview.html`
- `templates/dashboard/_filter_activity.html`
- `templates/dashboard/_filter_screening.html`
- `templates/dashboard/_filter_training.html`
- `templates/dashboard/_filter_case.html`

**New files (previous round: deep analytics / budget utilization):**
- `dashboard/analytics.py` — age-bucketing, referral-rate, trend, budget-utilization helpers
- `dashboard/migrations/0002_activityreport_cost_and_more.py`
- `templates/dashboard/budget_list.html`, `templates/dashboard/budget_form.html`
- `templates/dashboard/training_form.html`

**Modified files (across both rounds):**
- `dashboard/models.py` — added `cost` to `ActivityReport`/`TrainingProgram`, added `BudgetAllocation` model, added `program` FK to the screening base model
- `dashboard/views.py` — rewritten: every dashboard now has a shared `_<dashboard>_data(request)` function applying filters once, reused by the HTML view, CSV export, and PDF export; added Training create/edit views and Budget Allocation views
- `dashboard/urls.py` — added budget routes, Training create/edit routes, and CSV+PDF export routes for every dashboard
- `dashboard/forms.py` — added `BudgetAllocationForm`, `TrainingProgramForm`
- `dashboard/admin.py` — registered `BudgetAllocation`, added `cost` to list displays
- `dashboard/importers.py` — screening imports now link each record to a `Program` (for portfolio/program-wise analysis)
- `dashboard/utils.py` — added `scope_budget_qs()` for role-scoped budget visibility
- `dashboard/tests.py` — added tests for analytics helpers, filters, exports, and budget scoping (72 tests total, up from 52)
- `templates/base.html` — added "Budget Allocations" to the Admin nav menu
- `templates/dashboard/overview.html` — full rebuild: combined KPIs, region/portfolio tables, age/gender chart, filter bar, CSV+PDF export buttons
- `templates/dashboard/activity_dashboard.html` — full rebuild: budget card, region/portfolio/program charts, yearly trend, filter bar, CSV+PDF export
- `templates/dashboard/screening_dashboard.html` — full rebuild: referral-rate column, age/gender chart, region/yearly trend, filter bar, CSV+PDF export
- `templates/dashboard/training_dashboard.html` — full rebuild: attendance stats, top trainers, budget card, filter bar, CSV+PDF export
- `templates/dashboard/case_dashboard.html` — full rebuild: closure rate, avg. days-to-closure, referral sources, case-manager workload, filter bar, CSV+PDF export
- `templates/dashboard/activity_list.html` — added Cost column
- `templates/dashboard/training_list.html` — added "Add Training" button, Export CSV link
- `templates/dashboard/training_detail.html` — added Edit link, Cost field
- `static/css/style.css` — added `.metric-card` KPI styling and `@media print` rules
- `requirements.txt` — added `matplotlib`, `reportlab`

**Unchanged since the first zip:** `core/` app in full (users, roles, geography, permissions, audit log), `dashboard/models.py`'s original 10 screening models + `ActivityReport`/`TrainingProgram`/`CaseRecord` base fields, the bulk Excel/CSV importer's header-mapping logic, and all authentication/user-management templates.

## 12. A note on project scaffolding files

`health_dms/settings.py`, `health_dms/urls.py`, `health_dms/wsgi.py`,
`health_dms/asgi.py`, and the various `__init__.py` package markers are
standard Django project scaffolding wired up to match everything referenced
above (custom `AUTH_USER_MODEL = "core.User"`, the SQLite/Postgres switch,
Whitenoise for static files, the `templates/` and `static/` directories,
`core.context_processors.role_context`, `core.middleware.AuditLogMiddleware`,
and the login/logout redirect URLs). Review `health_dms/settings.py`
against your own deployment needs (allowed hosts, secret key, email backend,
etc.) before shipping to production.
