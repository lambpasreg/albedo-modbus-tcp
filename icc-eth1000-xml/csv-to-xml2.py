#!/usr/bin/env python3
"""
Replace ALL <BNObj> elements in an XML with rows from a CSV.

- Removes existing Dev/Config/Port/Node/BNObj entries.
- Creates new BNObj elements from CSV rows (one BNObj per row).
- Writes only the tags that appear in the CSV header (in the same order).
- Leaves the rest of the project XML unchanged.

Designed for files where BNObj live at:
  Proj -> Dev -> Config -> Port -> Node -> BNObj
(Adjust NODE_XPATH if your structure differs.)
"""

from pathlib import Path
import xml.etree.ElementTree as ET
import csv
import shutil

# ---- Configuration ----
NODE_XPATH = "./Dev/Config/Port/Node"  # where BNObj are in your XML (ICC Eaton 9155)  # noqa
# -----------------------

def load_csv(csv_path):
    """Return (header, rows) where rows are list of dicts. Handles UTF-8 BOM."""
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise RuntimeError("CSV has no header.")
        header = [h.strip() for h in reader.fieldnames]
        rows = []
        for row in reader:
            rows.append({k.strip(): (v or "").strip() for k, v in row.items() if k is not None})
    return header, rows

def clear_existing_bnobj(node):
    """Remove all BNObj elements under the given node. Return count removed."""
    bnobjs = list(node.findall("BNObj"))
    for b in bnobjs:
        node.remove(b)
    return len(bnobjs)

def create_bnobj_from_row(parent, header, row, write_empty=True):
    """
    Create <BNObj> under parent using CSV header to decide which child tags to write.
    If write_empty=False, skip tags where row value is empty.
    """
    bn = ET.SubElement(parent, "BNObj")
    for col in header:
        tag = col.strip()
        if not tag:
            continue
        val = row.get(tag, "")
        if not write_empty and val == "":
            continue
        child = ET.SubElement(bn, tag)
        child.text = val
    return bn

def replace_bnobj_from_csv(xml_in, csv_in, xml_out=None, write_empty=True, pretty=True, backup=True):
    xml_in = Path(xml_in)
    if xml_out is None:
        xml_out = xml_in.with_name(f"{xml_in.stem}_updated{xml_in.suffix}")

    if backup:
        shutil.copy2(xml_in, xml_in.with_suffix(xml_in.suffix + ".bak"))

    # Parse XML and locate BNObj container
    tree = ET.parse(xml_in)
    root = tree.getroot()
    node = root.find(NODE_XPATH)
    if node is None:
        raise RuntimeError(f"Could not find BNObj container at XPATH: {NODE_XPATH}")

    # Load CSV
    header, rows = load_csv(csv_in)
    if not rows:
        raise RuntimeError("CSV contains no data rows; refusing to wipe BNObj to empty.")

    # 1) Delete all existing BNObj
    removed = clear_existing_bnobj(node)

    # 2) Re-create BNObj from CSV (in order)
    for r in rows:
        create_bnobj_from_row(node, header, r, write_empty=write_empty)

    # Pretty print (Python 3.9+)
    if pretty and hasattr(ET, "indent"):
        ET.indent(tree, space="  ", level=0)

    tree.write(xml_out, encoding="utf-8", xml_declaration=True)

    print(f"Replaced BNObj successfully.")
    print(f"- Removed BNObj: {removed}")
    print(f"- Added BNObj:   {len(rows)}")
    print(f"Output file:     {xml_out}")

if __name__ == "__main__":
    # Example usage:
    replace_bnobj_from_csv(
        xml_in="ICC Eaton9155_good.xml",
        csv_in="albedo_1.csv",          # your CSV with BNObj rows
        xml_out="ICC Eaton9155_good_updated.xml",
        write_empty=True,                   # write empty tags if CSV value is blank
        pretty=True,
        backup=True
    )
