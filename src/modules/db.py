import asyncpg
from enum import Enum

class Tables(Enum):
    PROJECTS    = "projects"
    IMAGES      = "images"
    DAST        = "dast"

class ProjectColumns(Enum):
    ID                  = "id"
    IS_ACTIVE           = "is_active"
    GITLAB_URL          = "gitlab_url"
    GITLAB_BRANCH       = "gitlab_branch"
    DD_PROJECT_ID       = "dd_project_id"
    LAST_SCAN_AT        = "last_scan_at"
    TEAM                = "team"

class ImageColumns(Enum):
    ID              = "id"
    IS_ACTIVE       = "is_active"
    PROJECT_ID      = "project_id"
    IMAGE_URL       = "image_url"
    ENGAGEMENT_ID   = "engagement_id"
    LAST_SCAN_AT    = "last_scan_at"

class DastColumns(Enum):
    ID              = "id"
    PROJECT_ID      = "project_id"
    PARAMS          = "params"
    LAST_SCAN_AT    = "last_scan_at"

class Database:
    def __init__(self, conn_str: str):
        self.conn_str = conn_str
        self.conn = None

    async def connect(self):
        self.conn = await asyncpg.create_pool(self.conn_str)
    
    async def close(self):
        if self.conn:
            await self.conn.close()
    
    async def fetch_row(self, table: Tables, column: Enum, value: str) -> dict | None:
        if not self.conn:
            await self.connect()
        
        query = f"SELECT * FROM {table.value} WHERE {column.value} = $1 LIMIT 1"
        row = await self.conn.fetchrow(query, value)
        return dict(row) if row else None
    
    async def fetch_rows(self, table: Tables, column: Enum, value: str) -> list[dict] | None:
        if not self.conn:
            await self.connect()
        
        query = f"SELECT * FROM {table.value} WHERE {column.value} = $1"
        rows = await self.conn.fetch(query, value)
        return [dict(row) for row in rows] if rows != None else None
    
    async def fetch_rows_page(self, table: Tables, offset: int = 0, limit: int = 1) -> list[dict] | None:
        if not self.conn:
            await self.connect()

        query = f"SELECT * FROM {table.value} OFFSET $1 LIMIT $2"
        rows = await self.conn.fetch(query, offset, limit)
        return [dict(row) for row in rows] if rows != None else None

    async def fetch_rows_in(self, table: Tables, column: Enum, values: list[str], positive_in: bool) -> list[dict] | None:
        if not self.conn:
            await self.connect()
        filter_string = f"IN ({', '.join(values)})" if positive_in else f"NOT IN ({', '.join(values)})"
        query = f"SELECT * FROM {table.value} WHERE {column.value} {filter_string}"
        rows = await self.conn.fetch(query)
        return [dict(row) for row in rows] if rows != None else None
    
    async def insert_row(self, table: Tables, data: dict) -> None:
        if not self.conn:
            await self.connect()
        
        columns = ', '.join(k.value for k in data.keys())
        values_placeholders = ', '.join(f'${i+1}' for i in range(len(data)))
        values = tuple(data.values())
        
        query = f"INSERT INTO {table.value} ({columns}) VALUES ({values_placeholders})"
        await self.conn.execute(query, *values)
    
    async def delete_rows(self, table: Tables, column: Enum, values: list[str]) -> None:
        if not self.conn:
            await self.connect()

        query = f"DELETE FROM {table.value} WHERE {column.value} IN ({', '.join(values)})"
        await self.conn.execute(query)

    async def update_row(self, table: Tables, filter_column: Enum, filter_value: str, column: Enum, value: str) -> None:
        if not self.conn:
            await self.connect()

        query = f"UPDATE {table.value} SET {column.value} = $1 WHERE {filter_column.value} = $2"
        await self.conn.execute(query, value, filter_value)