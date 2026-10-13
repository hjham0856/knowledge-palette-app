from .workspace import Workspace, extract_wikilinks


def local_graph(ws: Workspace, path: str) -> dict:
    center = ws.safe_note_path(path)
    if not center.is_file():
        raise FileNotFoundError("note not found")
    center_path = str(center.relative_to(ws.root / "notes"))
    outgoing = set()
    unresolved = {}
    for target, _alias in extract_wikilinks(center.read_text(encoding="utf-8")):
        status, matches = ws.resolve_target(target)
        paths = [str(p.relative_to(ws.root / "notes")) for p in matches]
        if status == "ok":
            outgoing.add(paths[0])
        else:
            unresolved[target] = {"target": target, "status": status, "matches": paths}
    incoming = {note["path"] for note in ws.backlinks(center_path)}
    # 자기 링크는 다른 Note와의 연결이 아니므로 중심 노드만 표시한다.
    neighbors = sorted((outgoing | incoming) - {center_path})
    nodes = [{"path": center_path, "name": center.stem}]
    edges = []
    for neighbor in neighbors:
        nodes.append({"path": neighbor, "name": ws.safe_note_path(neighbor).stem})
        both = neighbor in outgoing and neighbor in incoming
        edges.append({
            "source": center_path if neighbor in outgoing else neighbor,
            "target": neighbor if neighbor in outgoing else center_path,
            "direction": "both" if both else "outgoing" if neighbor in outgoing else "incoming",
            "bidirectional": both,
        })
    return {"center": center_path, "nodes": nodes, "edges": edges, "unresolved": list(unresolved.values())}
