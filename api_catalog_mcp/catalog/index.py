from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from .model import Operation, Schema


class CatalogIndex:
    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def close(self) -> None:
        self._conn.close()

    def reset(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            DROP TABLE IF EXISTS operations;
            DROP TABLE IF EXISTS schemas;
            DROP TABLE IF EXISTS ops_fts;
            DROP TABLE IF EXISTS schemas_fts;
            DROP TABLE IF EXISTS op_embeddings;

            CREATE TABLE operations (
                id TEXT PRIMARY KEY,
                spec_id TEXT NOT NULL,
                operation_id TEXT,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                summary TEXT,
                description TEXT,
                tags TEXT,
                data TEXT NOT NULL
            );

            CREATE TABLE schemas (
                id TEXT PRIMARY KEY,
                spec_id TEXT NOT NULL,
                schema_name TEXT NOT NULL,
                description TEXT,
                data TEXT NOT NULL
            );

            CREATE INDEX operations_spec_id ON operations(spec_id);
            CREATE INDEX operations_opid ON operations(spec_id, operation_id);
            CREATE INDEX operations_path_method ON operations(spec_id, path, method);
            CREATE INDEX schemas_spec_id ON schemas(spec_id);
            CREATE INDEX schemas_name ON schemas(spec_id, schema_name);

            CREATE VIRTUAL TABLE ops_fts USING fts5(
                id UNINDEXED,
                spec_id UNINDEXED,
                operation_id,
                method,
                path,
                summary,
                description,
                tags,
                content
            );

            CREATE VIRTUAL TABLE schemas_fts USING fts5(
                id UNINDEXED,
                spec_id UNINDEXED,
                schema_name,
                description,
                content
            );

            CREATE TABLE op_embeddings (
                id TEXT PRIMARY KEY,
                dim INTEGER NOT NULL,
                vector BLOB NOT NULL
            );
            """
        )
        self._conn.commit()

    def is_ready(self) -> bool:
        cur = self._conn.cursor()
        row = cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='operations'"
        ).fetchone()
        return row is not None

    def add_operations(self, operations: Iterable[Operation]) -> None:
        cur = self._conn.cursor()
        for op in operations:
            tags = " ".join(op.tags)
            op_json = json.dumps(op.operation, ensure_ascii=True, sort_keys=True)
            cur.execute(
                """
                INSERT INTO operations
                (id, spec_id, operation_id, method, path, summary, description, tags, data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    op.op_key,
                    op.spec_id,
                    op.operation_id,
                    op.method,
                    op.path,
                    op.summary,
                    op.description,
                    tags,
                    op_json,
                ),
            )
            content = " ".join(
                str(part)
                for part in [
                    op.operation_id,
                    op.method,
                    op.path,
                    op.summary,
                    op.description,
                    tags,
                ]
                if part
            )
            cur.execute(
                """
                INSERT INTO ops_fts
                (id, spec_id, operation_id, method, path, summary, description, tags, content)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    op.op_key,
                    op.spec_id,
                    op.operation_id,
                    op.method,
                    op.path,
                    op.summary,
                    op.description,
                    tags,
                    content,
                ),
            )
        self._conn.commit()

    def add_schemas(self, schemas: Iterable[Schema]) -> None:
        cur = self._conn.cursor()
        for schema in schemas:
            schema_json = json.dumps(schema.schema, ensure_ascii=True, sort_keys=True)
            cur.execute(
                """
                INSERT INTO schemas
                (id, spec_id, schema_name, description, data)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    schema.schema_key,
                    schema.spec_id,
                    schema.schema_name,
                    schema.description,
                    schema_json,
                ),
            )
            content = " ".join(
                str(part)
                for part in [schema.schema_name, schema.description]
                if part
            )
            cur.execute(
                """
                INSERT INTO schemas_fts
                (id, spec_id, schema_name, description, content)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    schema.schema_key,
                    schema.spec_id,
                    schema.schema_name,
                    schema.description,
                    content,
                ),
            )
        self._conn.commit()

    def search_operations(
        self, query: str, spec_id: str | None = None, limit: int = 25
    ) -> list[dict[str, Any]]:
        query = _sanitize_fts_query(query)
        if not query:
            return []
        cur = self._conn.cursor()
        params: list[Any] = [query]
        sql = (
            "SELECT id, spec_id, operation_id, method, path, summary, description, tags, "
            "bm25(ops_fts) AS score, "
            "snippet(ops_fts, 8, '[', ']', '...', 12) AS snippet "
            "FROM ops_fts WHERE ops_fts MATCH ?"
        )
        if spec_id:
            sql += " AND spec_id = ?"
            params.append(spec_id)
        sql += " ORDER BY bm25(ops_fts), spec_id, path, method, operation_id LIMIT ?"
        params.append(limit)
        rows = cur.execute(sql, params).fetchall()
        return [self._row_to_operation_match(row) for row in rows]

    def search_schemas(self, query: str, spec_id: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        query = _sanitize_fts_query(query)
        if not query:
            return []
        cur = self._conn.cursor()
        params: list[Any] = [query]
        sql = (
            "SELECT id, spec_id, schema_name, description "
            "FROM schemas_fts WHERE schemas_fts MATCH ?"
        )
        if spec_id:
            sql += " AND spec_id = ?"
            params.append(spec_id)
        sql += " ORDER BY bm25(schemas_fts), spec_id, schema_name LIMIT ?"
        params.append(limit)
        rows = cur.execute(sql, params).fetchall()
        return [self._row_to_schema_match(row) for row in rows]

    def get_operation_by_operation_id(
        self, spec_id: str, operation_id: str
    ) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            """
            SELECT id, spec_id, operation_id, method, path, summary, description, tags, data
            FROM operations WHERE spec_id = ? AND operation_id = ?
            """,
            (spec_id, operation_id),
        ).fetchone()
        return self._row_to_operation(row) if row else None

    def get_operation_by_path_method(
        self, spec_id: str, path: str, method: str
    ) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            """
            SELECT id, spec_id, operation_id, method, path, summary, description, tags, data
            FROM operations WHERE spec_id = ? AND path = ? AND method = ?
            """,
            (spec_id, path, method),
        ).fetchone()
        return self._row_to_operation(row) if row else None

    def get_operation_by_endpoint_id(self, endpoint_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            """
            SELECT id, spec_id, operation_id, method, path, summary, description, tags, data
            FROM operations WHERE id = ?
            """,
            (endpoint_id,),
        ).fetchone()
        return self._row_to_operation(row) if row else None

    def get_operation_match_by_id(self, endpoint_id: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            """
            SELECT id, spec_id, operation_id, method, path, summary, description, tags
            FROM operations WHERE id = ?
            """,
            (endpoint_id,),
        ).fetchone()
        return self._row_to_operation_match(row) if row else None

    def get_schema(self, spec_id: str, schema_name: str) -> dict[str, Any] | None:
        cur = self._conn.cursor()
        row = cur.execute(
            """
            SELECT id, spec_id, schema_name, description, data
            FROM schemas WHERE spec_id = ? AND schema_name = ?
            """,
            (spec_id, schema_name),
        ).fetchone()
        return self._row_to_schema(row) if row else None

    def _row_to_operation_match(self, row: sqlite3.Row) -> dict[str, Any]:
        tags = row["tags"].split() if row["tags"] else []
        score = row["score"] if "score" in row.keys() else None
        snippet = row["snippet"] if "snippet" in row.keys() else None
        return {
            "endpointId": row["id"],
            "specId": row["spec_id"],
            "operationId": row["operation_id"],
            "method": row["method"],
            "path": row["path"],
            "summary": row["summary"],
            "description": row["description"],
            "tags": tags,
            "score": score,
            "matchSnippet": snippet,
        }

    def _row_to_schema_match(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "specId": row["spec_id"],
            "schemaName": row["schema_name"],
            "description": row["description"],
        }

    def _row_to_operation(self, row: sqlite3.Row) -> dict[str, Any]:
        tags = row["tags"].split() if row["tags"] else []
        return {
            "specId": row["spec_id"],
            "operationId": row["operation_id"],
            "method": row["method"],
            "path": row["path"],
            "summary": row["summary"],
            "description": row["description"],
            "tags": tags,
            "operation": json.loads(row["data"]),
        }

    def _row_to_schema(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "specId": row["spec_id"],
            "schemaName": row["schema_name"],
            "description": row["description"],
            "schema": json.loads(row["data"]),
        }

    def add_operation_embeddings(self, embeddings: list[tuple[str, int, bytes]]) -> None:
        cur = self._conn.cursor()
        cur.executemany(
            """
            INSERT OR REPLACE INTO op_embeddings (id, dim, vector)
            VALUES (?, ?, ?)
            """,
            embeddings,
        )
        self._conn.commit()

    def load_operation_embeddings(self) -> list[tuple[str, int, bytes]]:
        cur = self._conn.cursor()
        rows = cur.execute(
            "SELECT id, dim, vector FROM op_embeddings ORDER BY id"
        ).fetchall()
        return [(row["id"], row["dim"], row["vector"]) for row in rows]


def _sanitize_fts_query(query: str) -> str:
    cleaned = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in query.strip())
    cleaned = " ".join(cleaned.split())
    if not cleaned:
        return ""
    return f"\"{cleaned}\""
