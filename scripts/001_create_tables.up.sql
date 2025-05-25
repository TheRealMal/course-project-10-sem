CREATE TABLE IF NOT EXISTS projects (
    id                  BIGSERIAL   PRIMARY KEY,
    is_active           BOOLEAN     NOT NULL,
    gitlab_url          TEXT        NOT NULL,
    gitlab_branch       TEXT        NOT NULL,
    dd_project_id       BIGINT      NOT NULL UNIQUE,
    last_scan_at        DATE        NULL,
    team                TEXT        NOT NULL
);

CREATE TABLE IF NOT EXISTS images (
    id              BIGSERIAL   PRIMARY KEY,
    is_active       BOOLEAN     NOT NULL,
    project_id      BIGINT      NOT NULL REFERENCES projects(dd_project_id),
    image_url       TEXT        NOT NULL,
    engagement_id   BIGINT      NOT NULL,
    last_scan_at    DATE        NULL
);

CREATE TABLE IF NOT EXISTS dast (
    id              BIGSERIAL   PRIMARY KEY,
    project_id      BIGINT      NOT NULL REFERENCES projects(dd_project_id),
    params          TEXT        NOT NULL,
    last_scan_at    DATE        NULL
);