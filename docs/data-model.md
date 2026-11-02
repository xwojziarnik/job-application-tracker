# Data model

Tables and the relationships between them. Decisions referenced as `D-XX` are in
[`decisions.md`](decisions.md); the order of work is in [`roadmap.md`](roadmap.md).

| Table | Status |
|---|---|
| `companies` | Implemented (stage 2, step 1) |
| `job_offers`, `tags`, `job_offer_tags` | Planned (stage 2, step 2) |
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
        uuid company_id FK
        varchar url UK "normalised"
        varchar source "D-14"
        varchar seniority "D-15"
        varchar work_mode "D-14"
        int salary_min "nullable, B2B net per month"
        int salary_max "nullable"
        varchar(3) currency "nullable"
        date posted_on "nullable"
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
only for `companies` to keep the diagram readable.

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
| `job_offers` | normalised URL | unique constraint | D-05 |
| `tags` | normalised name | unique constraint | D-09 |
| `applications` | one active application per offer | partial unique index on `job_offer_id` for non-final statuses | D-06, D-16 |
| `cv_documents` | file content (`sha256`) and object key | unique constraints | D-19 |

## Files outside the database

CV files are stored in **SeaweedFS** through the S3 API, in a private bucket; the database
keeps only their metadata in `cv_documents`. The two stores have no shared transaction, so
the order of writes and the clean-up of orphaned objects are described in D-19.
