# Data model

Tables and the relationships between them. Decisions referenced as `D-XX` are in
[`decisions.md`](decisions.md); the order of work is in [`roadmap.md`](roadmap.md).

| Table | Status |
|---|---|
| `companies` | Implemented (stage 2, step 1) |
| `job_offers` | Implemented (stage 2, step 2: table only, no endpoints yet) |
| `tags`, `job_offer_tags` | Planned (stage 2, step 2) |
| `applications` | Planned (stage 2, step 3) |
| `cv_documents` (files in SeaweedFS) | Planned (stage 2, step 4, D-19) |

Columns of the planned tables are a sketch based on the decisions so far; their exact
names, types and required fields are decided in their own step and this file is updated
then. Keep the diagram in sync with the models whenever a migration changes the schema.

```mermaid
erDiagram
    companies ||--o{ job_offers : "posts (ON DELETE RESTRICT)"
    job_offers ||--o{ job_offer_tags : "is tagged with"
    tags ||--o{ job_offer_tags : "labels"
    job_offers ||--o{ applications : "receives (ON DELETE CASCADE)"
    cv_documents |o--o{ applications : "sent with (ON DELETE RESTRICT)"

    companies {
        uuid id PK
        varchar(200) name UK "unique on lower(name)"
        varchar(2048) website "nullable"
        varchar(200) location "nullable"
        varchar(100) industry "nullable"
        varchar(2000) notes "nullable"
        boolean is_active "default true"
        timestamptz created_at
        timestamptz updated_at
    }

    job_offers {
        uuid id PK
        uuid company_id FK "cannot change after creation"
        varchar(200) title
        varchar(2048) url UK "normalised before saving"
        varchar(20) source "CHECK, D-20"
        varchar(20) seniority "CHECK, D-15"
        varchar(20) work_mode "CHECK, D-14"
        varchar(200) location "nullable"
        int salary_min "nullable, B2B net per month"
        int salary_max "nullable"
        varchar(10) currency "nullable, CHECK"
        date posted_on "nullable"
        varchar(20000) description "nullable"
        varchar(2000) notes "nullable"
        timestamptz created_at
        timestamptz updated_at
    }

    tags {
        uuid id PK
        varchar(50) name UK "normalised"
    }

    job_offer_tags {
        uuid job_offer_id PK, FK
        uuid tag_id PK, FK
    }

    applications {
        uuid id PK
        uuid job_offer_id FK "one active per offer"
        uuid cv_document_id FK "nullable"
        varchar status "D-16"
        date sent_on "nullable"
    }

    cv_documents {
        uuid id PK
        varchar object_key UK "cv/{uuid}.pdf in SeaweedFS"
        varchar file_name "as uploaded, metadata only"
        varchar content_type "application/pdf"
        int size_bytes "at most 5 MB"
        char(64) sha256 UK "same file reuses the document"
    }
```

Every table also gets `created_at` and `updated_at` from `TimestampMixin`; they are shown
only for the implemented tables to keep the diagram readable.

## Relationships

| From | To | Cardinality | On delete of the parent | Decisions |
|---|---|---|---|---|
| `companies` | `job_offers` | one company, many offers | `RESTRICT`: companies are never deleted, only deactivated; offers of an inactive company are hidden from lists | D-04, D-10 |
| `job_offers` | `tags` | many to many, through `job_offer_tags` | the offer's links to tags are deleted; tags stay | D-09 |
| `job_offers` | `applications` | one offer, many applications over time, at most one active | `CASCADE`: deleting an offer deletes its applications | D-04, D-06, D-16 |
| `cv_documents` | `applications` | one CV version, used by any number of applications; an application has at most one CV (optional) | `RESTRICT`: a CV used by an application cannot be deleted; deleting an application keeps its CV | D-19 |

## Uniqueness

| Table | Rule | Enforced by | Decisions |
|---|---|---|---|
| `companies` | name, regardless of case | unique index `uq_companies_lower_name` on `lower(name)` | D-05 |
| `job_offers` | normalised URL | unique constraint `uq_job_offers_url` | D-05 |
| `tags` | normalised name | unique constraint | D-09 |
| `applications` | one active application per offer | partial unique index on `job_offer_id` for non-final statuses | D-06, D-16 |
| `cv_documents` | file content (`sha256`) and object key | unique constraints | D-19 |

## Check constraints

Rules the database enforces on its own, also for rows written outside the application.
Names follow the naming convention in `db/base.py` (`ck_<table>_<name>`).

| Table | Constraint | Rule | Decisions |
|---|---|---|---|
| `job_offers` | `ck_job_offers_source` | `source` is one of the offer sources | D-02, D-20 |
| `job_offers` | `ck_job_offers_seniority` | `seniority` is one of the seniority values, single or combined | D-02, D-15 |
| `job_offers` | `ck_job_offers_work_mode` | `work_mode` is `remote`, `hybrid` or `office` | D-02, D-14 |
| `job_offers` | `ck_job_offers_currency` | `currency` is `PLN`, `EUR` or `USD` | D-02, D-14 |
| `job_offers` | `ck_job_offers_salary_range` | no salary at all, or `salary_min`, `salary_max` and `currency` all set with `0 < salary_min <= salary_max` | D-03 |

Enumerations store their values (`mid_senior`), not the Python member names
(`MID_SENIOR`), so SQL, the API and the code use the same strings (D-02).

## Files outside the database

CV files are stored in **SeaweedFS** through the S3 API, in a private bucket; the database
keeps only their metadata in `cv_documents`. The two stores have no shared transaction, so
the order of writes and the clean-up of orphaned objects are described in D-19.
