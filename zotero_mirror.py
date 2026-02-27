import sqlite3
import os
import pathlib
import shutil

# --- CONFIGURATION ---
ZOTERO_DATA_DIR = pathlib.Path("/Users/danielsinausia/Documents/Zotero")
MIRROR_DIR = pathlib.Path("/Users/danielsinausia/Documents/Zotero/ZoteroMirror")
USE_SYMLINKS = False  # False = copy files instead, True = uses symlinks not to double the pdf, but doesn't work well with iCloud
# -----------------------

DB_PATH = ZOTERO_DATA_DIR / "zotero.sqlite"
STORAGE_DIR = ZOTERO_DATA_DIR / "storage"


def get_collections(cursor):
    cursor.execute("""
        SELECT collectionID, collectionName, parentCollectionID
        FROM collections
        WHERE libraryID = 1
    """)
    return {row[0]: {"name": row[1], "parent": row[2]} for row in cursor.fetchall()}


def build_path(col_id, collections):
    col = collections[col_id]
    name = col["name"]
    if col["parent"]:
        return build_path(col["parent"], collections) / name
    return pathlib.Path(name)


def get_items_in_collections(cursor):
    cursor.execute("""
        SELECT ci.collectionID, i.itemID, idv.value AS title
        FROM collectionItems ci
        JOIN items i ON ci.itemID = i.itemID
        LEFT JOIN itemData id ON i.itemID = id.itemID AND id.fieldID = (
            SELECT fieldID FROM fields WHERE fieldName = 'title'
        )
        LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
        WHERE i.itemTypeID != 14  -- exclude attachments as top-level items
    """)
    return cursor.fetchall()


def get_attachments(cursor, item_id):
    cursor.execute("""
        SELECT ia.path, i.key
        FROM itemAttachments ia
        JOIN items i ON ia.itemID = i.itemID
        WHERE ia.parentItemID = ? AND ia.contentType = 'application/pdf'
    """, (item_id,))
    return cursor.fetchall()


def sanitize(name):
    if not name:
        return "Untitled"
    return "".join(c if c not in r'\/:*?"<>|' else "_" for c in name).strip()[:80]


def main():
    # Copy DB to avoid conflicts with a running Zotero instance
    tmp_db = pathlib.Path("/tmp/zotero_mirror.sqlite")
    shutil.copy2(DB_PATH, tmp_db)

    conn = sqlite3.connect(tmp_db)
    cursor = conn.cursor()

    collections = get_collections(cursor)
    items = get_items_in_collections(cursor)

    # Wipe and recreate the mirror directory
    if MIRROR_DIR.exists():
        shutil.rmtree(MIRROR_DIR)
    MIRROR_DIR.mkdir(parents=True, exist_ok=True)

    linked = 0
    for col_id, item_id, title in items:
        col_path = build_path(col_id, collections)
        dest_dir = MIRROR_DIR / col_path
        dest_dir.mkdir(parents=True, exist_ok=True)

        attachments = get_attachments(cursor, item_id)
        for path, key in attachments:
            if path and path.startswith("storage:"):
                filename = path[len("storage:"):]
                src = STORAGE_DIR / key / filename
            elif path:
                src = pathlib.Path(path)
            else:
                continue

            if not src.exists():
                continue

            dest = dest_dir / f"{sanitize(title)}.pdf"

            # Handle duplicates
            counter = 1
            while dest.exists() and dest.resolve() != src.resolve():
                dest = dest_dir / f"{sanitize(title)}_{counter}.pdf"
                counter += 1

            if dest.exists():
                continue

            if USE_SYMLINKS:
                os.symlink(src, dest)
            else:
                shutil.copy2(src, dest)
            linked += 1

    conn.close()
    print(f"Done. {linked} PDFs {'linked' if USE_SYMLINKS else 'copied'}.")


if __name__ == "__main__":
    main()