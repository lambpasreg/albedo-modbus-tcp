#!/usr/bin/env python3
"""
Update BNObj entries in an XML file from a CSV file (reverse of BNObj export).

- Matches BNObjs by 'Name' (default) or by composite key ('VAddr+DBAddr').
- Updates only the columns found in the CSV header; can optionally skip empty values.
- Can add new BNObj elements if they don't exist (allow_add=True).

Tested with a structure like:
  Proj -> Dev -> Config -> Port -> Node -> BNObj
(adjust NODE_XPATH if yours differs)
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import csv
import shutil
from collections import Counter

# ---------- Configuration ----------
# XPath to the container Node holding BNObj elements (matches your file)
NODE_XPATH = "./Dev/Config/Port/Node"  # tailored for ICC Eaton9155_good.xml
# Default field set we care about (will only update the ones present in CSV header)
ALL_FIELDS = ["Name", "VAddr", "DBAddr", "DSize", "Float", "Signed", "Units", "Mask"]
# -----------------------------------

def load_csv_rows(csv_path):
    """Read CSV into a list of dicts; trims whitespace; handles UTF-8 BOM."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in reader.fieldnames] if reader.fieldnames else []
        rows = []
        for row in reader:
            clean = {}
            for k, v in row.items():
                if k is None:
                    continue
                k2 = k.strip()
                clean[k2] = (v or "").strip()
            rows.append(clean)
    return header, rows

def index_bnobjs(node, key_mode="Name"):
    """
    Build an index of BNObj elements keyed by:
      - 'Name': a single string key of the Name text
      - 'VAddr+DBAddr': a tuple (VAddr, DBAddr)
    """
    idx = {}
    for b in node.findall("BNObj"):
        name = (b.findtext("Name", "") or "").strip()
        vaddr = (b.findtext("VAddr", "") or "").strip()
        dbaddr = (b.findtext("DBAddr", "") or "").strip()

        if key_mode == "Name":
            if name:  # skip empty names
                idx[(name,)] = b
        elif key_mode == "VAddr+DBAddr":
            if vaddr or dbaddr:
                idx[(vaddr, dbaddr)] = b
        else:
            raise ValueError("key_mode must be 'Name' or 'VAddr+DBAddr'")
    return idx

def set_child_text(parent, tag, value):
    """Ensure child tag exists under parent and set its text to value (str)."""
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = value

def detect_duplicate_keys(rows, key_mode):
    """Return a list of duplicate keys from CSV (so we can warn/fail fast)."""
    keys = []
    for r in rows:
        if key_mode == "Name":
            keys.append((r.get("Name", "").strip(),))
        else:
            keys.append((r.get("VAddr", "").strip(), r.get("DBAddr", "").strip()))
    c = Counter(keys)
    return [k for k, n in c.items() if k and n > 1]

def update_from_csv(
    xml_in,
    csv_in,
    xml_out=None,
    key_mode="Name",        # 'Name' or 'VAddr+DBAddr'
    include_fields=None,    # if not None, update only these fields
    allow_add=False,        # add BNObj if CSV row not found in XML
    update_empty=False,     # if False, skip empty CSV values
    pretty=True,            # indent the output XML (Python 3.9+)
    backup=True             # write original backup as *.bak
):
    xml_in = Path(xml_in)
    if xml_out is None:
        xml_out = xml_in.with_name(xml_in.stem + "_updated" + xml_in.suffix)

    # Optional backup
    if backup:
        shutil.copy2(xml_in, xml_in.with_suffix(xml_in.suffix + ".bak"))

    # Parse XML and find the BNObj container node
    tree = ET.parse(xml_in)
    root = tree.getroot()
    node = root.find(NODE_XPATH)
    if node is None:
        raise RuntimeError(f"Could not locate BNObj node at '{NODE_XPATH}'. "
                           f"Adjust NODE_XPATH for your XML structure.")

    # Load CSV rows
    header, rows = load_csv_rows(csv_in)
    if not header:
        raise RuntimeError("CSV has no header. Expecting at least 'Name' or 'VAddr,DBAddr'.")

    # Determine which columns to update
    if include_fields is None:
        fields_to_update = [h for h in header if h in ALL_FIELDS]
    else:
        fields_to_update = [f for f in include_fields if f in header]

    # Guard against duplicate keys in the CSV
    dups = detect_duplicate_keys(rows, key_mode)
    if dups:
        raise RuntimeError(f"CSV contains duplicate keys for key_mode={key_mode}: {dups[:5]} "
                           f"{'(and more...)' if len(dups) > 5 else ''}")

    # Index existing BNObj elements
    idx = index_bnobjs(node, key_mode=key_mode)

    changes = []  # tuples: (key, tag, old, new)
    added = 0
    skipped = 0

    def get_row_key(r):
        if key_mode == "Name":
            return (r.get("Name", "").strip(),)
        else:
            return (r.get("VAddr", "").strip(), r.get("DBAddr", "").strip())

    for r in rows:
        key = get_row_key(r)
        if not any(key):  # empty key
            skipped += 1
            continue

        b = idx.get(key)
        if b is None:
            if not allow_add:
                skipped += 1
                continue
            # Create new BNObj
            b = ET.SubElement(node, "BNObj")
            # Ensure at least a Name is present if using VAddr+DBAddr as key
            if key_mode == "VAddr+DBAddr" and not r.get("Name"):
                r["Name"] = f"BNObj_{r.get('VAddr','')}_{r.get('DBAddr','')}"
            idx[key] = b
            added += 1

        # Update fields
        for tag in fields_to_update:
            new_val = r.get(tag, "")
            if not update_empty and new_val == "":
                continue
            old_val = (b.findtext(tag, "") or "")
            if old_val != new_val:
                set_child_text(b, tag, new_val)
                # Build a friendly key string for logging
                key_str = key[0] if key_mode == "Name" else f"{key[0]}+{key[1]}"
                changes.append((key_str, tag, old_val, new_val))

    # Pretty print (Python 3.9+)
    if pretty and hasattr(ET, "indent"):
        ET.indent(tree, space="  ", level=0)

    tree.write(xml_out, encoding="utf-8", xml_declaration=True)

    # Summary
    print(f"Updated XML written to: {xml_out}")
    print(f"Changed fields: {len(changes)}; Added BNObj: {added}; Skipped rows: {skipped}")
    for k, tag, old, new in changes[:20]:
        print(f"- {k}: {tag}: '{old}' -> '{new}'")
    if len(changes) > 20:
        print(f"... {len(changes)-20} more changes")

if __name__ == "__main__":
    # --- Example usages ---
    # 1) Match by Name (typical), don't add new entries, skip empty cells
    update_from_csv(
        xml_in="ICC Eaton9155_good.xml",
        csv_in="albedo_1.csv",
        xml_out="ICC Eaton9155_good_updated.xml",
        key_mode="Name",
        allow_add=False,
        update_empty=False
    )

    # 2) Match by (VAddr+DBAddr), allow adding new BNObjs, and update even empty cells
    # update_from_csv(
    #     xml_in="ICC Eaton9155_good.xml",
    #     csv_in="BNObj_points.csv",
    #     xml_out="ICC Eaton9155_good_updated.xml",
    #     key_mode="VAddr+DBAddr",
    #     allow_add=True,
    #     update_empty=True
    # )

    # 3) Update only specific fields (e.g., just Units and Float)
    # update_from_csv(
    #     xml_in="ICC Eaton9155_good.xml",
    #     csv_in="BNObj_points.csv",
    #     xml_out="ICC Eaton9155_good_updated.xml",
    #     key_mode="Name",
    #     include_fields=["Units", "Float"],
    #     allow_add=False,
    #     update_empty=False
    # )