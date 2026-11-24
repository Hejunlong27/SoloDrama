#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-way SoloDrama project importer for SoloDrama.

Reads a legacy SoloDrama workspace, copies its creative artifacts and media into
a new SoloDrama workspace, then writes a native ``solodramaCanvas`` JSON file.

The importer is intentionally standalone: it uses only the Python standard
library and does not import either application's source code.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_STAGES = {
    "script": "03-剧本",
    "assets": "04-资产",
    "storyboard": "05-分镜",
    "prompts": "06-提示词",
    "film": "07-成片",
    "compliance": "08-合规",
    "release": "09-发行",
}
STOP_WORDS = {"", "base", "基础", "基础造型", "空景", "主卡"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv"}
MIME_BY_SUFFIX = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".avif": "image/avif",
    ".bmp": "image/bmp", ".mp4": "video/mp4", ".webm": "video/webm",
    ".mov": "video/quicktime", ".mkv": "video/x-matroska",
}


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return default


def safe_token(value: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return token[:90] or "node"


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(value or "").lower())


def find_pack(source: Path, explicit: Path | None) -> Path | None:
    if explicit:
        return explicit.resolve()
    direct = source / "pack"
    if (direct / "pack.json").is_file():
        return direct
    candidates = sorted(source.rglob("pack.json"))
    candidates = [path.parent for path in candidates if "node_modules" not in path.parts]
    return candidates[0] if candidates else None


def load_layout(source: Path, explicit: Path | None) -> dict[str, Any]:
    path = explicit.resolve() if explicit else source / "layout.json"
    data = read_json(path, {}) if path.is_file() else {}
    stages = dict(DEFAULT_STAGES)
    if isinstance(data.get("stages"), dict):
        for key, value in data["stages"].items():
            if isinstance(value, str) and value.strip():
                stages[key] = value
    return {"path": str(path) if path.is_file() else "", "stages": stages}


def load_asset_catalog(pack: Path | None) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    catalog: dict[str, dict[str, Any]] = {}
    items: list[dict[str, Any]] = []
    if not pack:
        return catalog, items
    for name, kind in (("characters.json", "character"), ("scenes.json", "scene"), ("props.json", "prop")):
        doc = read_json(pack / "assets" / name, {}) or {}
        for item in doc.get("items", []) if isinstance(doc, dict) else []:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            record = {**item, "kind": kind}
            catalog[item["id"].upper()] = record
            items.append(record)
    return catalog, items


def load_episodes(pack: Path | None) -> list[dict[str, Any]]:
    if not pack:
        return []
    episodes = []
    for path in sorted((pack / "episodes").glob("ep*.json")):
        data = read_json(path, {}) or {}
        if isinstance(data, dict) and isinstance(data.get("shots"), list):
            data["_path"] = str(path)
            episodes.append(data)
    return episodes


def candidate_asset_files(asset_dir: Path, item: dict[str, Any], variant: dict[str, Any] | None) -> list[Path]:
    kind_dir = {"character": "characters", "scene": "scenes", "prop": "props"}.get(item.get("kind"), "props")
    root = asset_dir / kind_dir
    if not root.is_dir():
        return []
    ident = str(item.get("id") or "")
    name = str(item.get("name") or "")
    code = str((variant or {}).get("code") or "")
    files = [path for path in root.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
    scored: list[tuple[int, Path]] = []
    for path in files:
        stem_n = normalize(path.stem)
        if not stem_n.startswith(normalize(ident)):
            continue
        score = 10
        if normalize(name) and normalize(name) in stem_n:
            score += 10
        if code and code.lower() not in STOP_WORDS and normalize(code) in stem_n:
            score += 20
        elif code.lower() in STOP_WORDS and not any(normalize(other) in stem_n for other in ("look", "base", "变体")):
            score += 5
        scored.append((score, path))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name.lower()))
    return [path for _, path in scored]


def copy_file(source: Path, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite {destination}")
    shutil.copy2(source, destination)
    return destination.as_posix()


def copy_tree_files(source: Path, destination_root: Path, excluded: Iterable[Path] = ()) -> list[Path]:
    copied: list[Path] = []
    if not source.is_dir():
        return copied
    excluded_set = {path.resolve() for path in excluded}
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.resolve() in excluded_set:
            continue
        relative = path.relative_to(source)
        copied.append(Path(copy_file(path, destination_root / relative)))
    return copied


def text_node(node_id: str, label: str, content: str, position: dict[str, float], text_path: str | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "remote-textNode",
        "position": position,
        "data": {
            "label": label,
            **({"textPath": text_path} if text_path else {}),
            "outputs": {"text": {"dataType": "STRING", "value": content}},
        },
    }


def image_node(node_id: str, label: str, path: str, position: dict[str, float]) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "remote-imageNode",
        "position": position,
        "data": {
            "label": label,
            "outputs": {"image": {"dataType": "IMAGE", "value": {"url": path, "mimeType": MIME_BY_SUFFIX.get(Path(path).suffix.lower(), "image/png")}}},
        },
    }


def video_node(node_id: str, label: str, path: str, position: dict[str, float]) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "remote-videoNode",
        "position": position,
        "data": {
            "label": label,
            "outputs": {"video": {"dataType": "VIDEO", "value": {"url": path, "mimeType": MIME_BY_SUFFIX.get(Path(path).suffix.lower(), "video/mp4")}}},
        },
    }


def video_generation_node(node_id: str, label: str, prompt: str, duration: Any, ratio: str, position: dict[str, float]) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "remote-videoGenerationNode",
        "position": position,
        "data": {
            "label": label,
            "prompt": prompt,
            "promptModel": [],
            "model": "",
            "duration": duration,
            "resolution": "",
            "ratio": ratio or "9:16",
            "mode": "",
            "generateAudio": True,
            "other": {},
        },
    }


def edge(edge_id: str, source: str, target: str, source_handle: str, target_handle: str) -> dict[str, Any]:
    return {
        "id": edge_id,
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
        "targetHandle": target_handle,
    }


def shot_text(shot: dict[str, Any], episode: dict[str, Any]) -> str:
    lines = [
        f"# {episode.get('title') or '未命名剧集'} · {shot.get('id') or '未命名镜头'}",
        "",
        f"- 集数：{episode.get('episode', '')}",
        f"- 时长：{shot.get('duration', '')} 秒",
        f"- 画幅：{shot.get('ratio', '')}",
        f"- 段内切点：{shot.get('shots_within', '')}",
        "",
        "## Cast（参考图顺序）",
    ]
    cast = shot.get("cast") if isinstance(shot.get("cast"), list) else []
    for index, item in enumerate(cast, 1):
        if not isinstance(item, dict):
            continue
        lines.append(f"{index}. {item.get('asset', '')}" + (f" / {item.get('variant')}" if item.get("variant") else ""))
    lines += ["", "## 分镜图提示词", str(shot.get("board_prompt") or ""), "", "## 视频提示词", str(shot.get("video_prompt") or "")]
    dialogue = shot.get("dialogue")
    if isinstance(dialogue, list) and dialogue:
        lines += ["", "## 台词", "```json", json.dumps(dialogue, ensure_ascii=False, indent=2), "```"]
    notes = shot.get("notes")
    if notes:
        lines += ["", "## 备注", str(notes)]
    return "\n".join(lines).strip() + "\n"


def find_board(asset_dir: Path, episode_key: str, shot_id: str) -> Path | None:
    roots = [asset_dir / "boards" / episode_key, asset_dir / "boards"]
    for root in roots:
        if not root.is_dir():
            continue
        matches = [path for path in root.rglob(f"{shot_id}.*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
        if matches:
            return sorted(matches, key=lambda path: len(path.as_posix()))[0]
    return None


def find_shot_video(film_dir: Path, episode_key: str, shot_id: str) -> Path | None:
    if not film_dir.is_dir():
        return None
    candidates = []
    for path in film_dir.rglob("*.mp4"):
        lowered = normalize(path.as_posix())
        if normalize(shot_id) in lowered and normalize(episode_key) in lowered:
            candidates.append(path)
    return sorted(candidates, key=lambda path: (len(path.parts), path.as_posix()))[0] if candidates else None


def find_release_videos(release_dir: Path) -> list[Path]:
    root = release_dir / "剧集"
    if not root.is_dir():
        return []
    return sorted(path for path in root.glob("Episode*.mp4") if path.is_file())


@dataclass
class BuildState:
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=lambda: {
        "scripts": 0, "assetImages": 0, "shots": 0, "boards": 0,
        "generationNodes": 0, "videos": 0, "releaseVideos": 0,
        "warnings": [], "missing": [],
    })
    y: float = 80

    def next_y(self) -> float:
        value = self.y
        self.y += 280
        return value


def run(source: Path, output: Path, layout_path: Path | None, pack_path: Path | None, canvas_name: str, dry_run: bool) -> dict[str, Any]:
    source = Path(source).resolve()
    output = Path(output)
    layout_path = Path(layout_path) if layout_path is not None else None
    pack_path = Path(pack_path) if pack_path is not None else None
    if not source.is_dir():
        raise ValueError(f"source is not a directory: {source}")
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"output directory must be absent or empty: {output}")
    layout = load_layout(source, layout_path)
    stages = layout["stages"]
    pack = find_pack(source, pack_path)
    asset_dir = source / stages["assets"]
    film_dir = source / stages["film"]
    release_dir = source / stages["release"]
    catalog, assets = load_asset_catalog(pack)
    episodes = load_episodes(pack)
    state = BuildState()

    if not dry_run:
        output.mkdir(parents=True, exist_ok=True)
        imported = output / "imported" / "solodrama"
        imported.mkdir(parents=True, exist_ok=True)
        if pack:
            copy_tree_files(pack, imported / "pack")
        for stage_key in ("script", "storyboard"):
            stage = source / stages[stage_key]
            if stage.is_dir():
                copy_tree_files(stage, imported / stage_key)
        for metadata in sorted(source.glob("*.json")):
            if metadata.name in {"layout.json", "model-plan.json", "project.json"}:
                copy_file(metadata, imported / "metadata" / metadata.name)

    # Scripts and storyboard documents become editable text nodes.
    script_nodes = 0
    for stage_key in ("script", "storyboard"):
        stage = source / stages[stage_key]
        if not stage.is_dir():
            continue
        for index, path in enumerate(sorted(stage.rglob("*.md"))):
            content = path.read_text(encoding="utf-8-sig", errors="replace")
            node_id = f"sdScript_{safe_token(stage_key)}_{index + 1:03d}"
            relative = path.relative_to(source).as_posix()
            body = f"<!-- {relative} -->\n\n{content}"
            text_path = f"assets/{node_id}/content.md"
            if not dry_run:
                destination = output / text_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(body, encoding="utf-8", newline="\n")
            state.nodes.append(text_node(node_id, f"{stage_key} · {path.stem}", body, {"x": 40, "y": state.next_y()}, None if dry_run else text_path))
            script_nodes += 1
    state.report["scripts"] = script_nodes

    # Build one image node per referenced asset variant. Reuse the first matching file.
    asset_nodes: dict[tuple[str, str], str] = {}
    asset_paths: dict[tuple[str, str], Path] = {}
    for item in assets:
        variants = item.get("variants") if isinstance(item.get("variants"), list) else [{"code": ""}]
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            key = (str(item.get("id", "")).upper(), str(variant.get("code", "")))
            matches = candidate_asset_files(asset_dir, item, variant)
            if not matches:
                state.report["missing"].append({"kind": "asset-image", "asset": key[0], "variant": key[1]})
                continue
            asset_paths[key] = matches[0]
    for key, path in asset_paths.items():
        node_id = f"sdAsset_{safe_token(key[0])}_{safe_token(key[1] or 'base')}"
        label = f"资产 {key[0]} · {key[1] or '基础'}"
        if not dry_run:
            destination = output / "imported" / "media" / "assets" / path.name
            copy_file(path, destination)
            relative = destination.relative_to(output).as_posix()
        else:
            relative = path.relative_to(source).as_posix()
        state.nodes.append(image_node(node_id, label, relative, {"x": 430, "y": state.next_y()}))
        asset_nodes[key] = node_id
        state.report["assetImages"] += 1

    # Episode shots: text node, board image node, video-generation prompt node, final video node.
    for ep_index, episode in enumerate(episodes):
        ep_key = f"ep{int(episode.get('episode', ep_index + 1)):02d}"
        for shot_index, shot in enumerate(episode.get("shots") or []):
            if not isinstance(shot, dict):
                continue
            shot_id = str(shot.get("id") or f"shot_{shot_index + 1:03d}")
            token = safe_token(f"{ep_key}_{shot_id}")
            y = state.next_y()
            text_id = f"sdShotText_{token}"
            generation_id = f"sdVideoGen_{token}"
            prompt = str(shot.get("video_prompt") or "")
            ratio = str(shot.get("ratio") or "9:16")
            duration = shot.get("duration")
            body = shot_text(shot, episode)
            text_path = f"assets/{text_id}/content.md"
            if not dry_run:
                destination = output / text_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(body, encoding="utf-8", newline="\n")
            state.nodes.append(text_node(text_id, f"{ep_key} · {shot_id} · 字段", body, {"x": 820, "y": y}, None if dry_run else text_path))
            state.nodes.append(video_generation_node(generation_id, f"{ep_key} · {shot_id} · 视频生成", prompt, duration, ratio, {"x": 1220, "y": y}))
            state.edges.append(edge(f"edge_{token}_prompt", text_id, generation_id, "text", "in"))
            state.report["shots"] += 1
            state.report["generationNodes"] += 1

            board = find_board(asset_dir, ep_key, shot_id)
            if board:
                board_id = f"sdBoard_{token}"
                if not dry_run:
                    destination = output / "imported" / "media" / "boards" / ep_key / board.name
                    copy_file(board, destination)
                    board_relative = destination.relative_to(output).as_posix()
                else:
                    board_relative = board.relative_to(source).as_posix()
                state.nodes.append(image_node(board_id, f"{ep_key} · {shot_id} · 分镜图", board_relative, {"x": 820, "y": y + 180}))
                # Board is Picture 1 and must be first.
                state.edges.append(edge(f"edge_{token}_board", board_id, generation_id, "image", "in"))
                state.report["boards"] += 1
            else:
                state.report["missing"].append({"kind": "board-image", "episode": ep_key, "shot": shot_id})

            for cast_index, cast in enumerate(shot.get("cast") or []):
                if not isinstance(cast, dict):
                    continue
                asset_id = str(cast.get("asset") or "").upper()
                asset = catalog.get(asset_id) or {}
                variants = asset.get("variants") if isinstance(asset.get("variants"), list) else []
                variant = str(cast.get("variant") or (variants[0].get("code") if variants and isinstance(variants[0], dict) else ""))
                image_id = asset_nodes.get((asset_id, variant))
                if image_id:
                    state.edges.append(edge(f"edge_{token}_cast_{cast_index + 1:02d}", image_id, generation_id, "image", "in"))
                else:
                    state.report["missing"].append({"kind": "cast-image", "episode": ep_key, "shot": shot_id, "asset": asset_id, "variant": variant})

            final_video = find_shot_video(film_dir, ep_key, shot_id)
            if final_video:
                video_id = f"sdVideo_{token}"
                if not dry_run:
                    destination = output / "imported" / "media" / "videos" / ep_key / shot_id / final_video.name
                    copy_file(final_video, destination)
                    video_relative = destination.relative_to(output).as_posix()
                else:
                    video_relative = final_video.relative_to(source).as_posix()
                state.nodes.append(video_node(video_id, f"{ep_key} · {shot_id} · 成片", video_relative, {"x": 1640, "y": y}))
                state.report["videos"] += 1

    for path in find_release_videos(release_dir):
        node_id = f"sdRelease_{safe_token(path.stem)}"
        if not dry_run:
            destination = output / "imported" / "media" / "release" / path.name
            copy_file(path, destination)
            relative = destination.relative_to(output).as_posix()
        else:
            relative = path.relative_to(source).as_posix()
        state.nodes.append(video_node(node_id, f"发行版 · {path.stem}", relative, {"x": 1640, "y": state.next_y()}))
        state.report["releaseVideos"] += 1

    canvas = {
        "solodramaCanvas": True,
        "nodes": state.nodes,
        "edges": state.edges,
        "viewport": {"x": 0, "y": 0, "zoom": 0.6},
    }
    state.report.update({
        "source": str(source),
        "output": str(output),
        "pack": str(pack) if pack else "",
        "layout": layout["path"],
        "nodeCount": len(state.nodes),
        "edgeCount": len(state.edges),
        "dryRun": dry_run,
    })
    if not dry_run:
        canvas_path = output / f"{canvas_name}.json"
        canvas_path.write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        ratios = [
            str(shot.get("ratio"))
            for episode in episodes
            for shot in episode.get("shots", [])
            if isinstance(shot, dict) and shot.get("ratio")
        ]
        ratio = ratios[0] if ratios else "9:16"
        try:
            ratio_width, ratio_height = (int(part) for part in ratio.split(":", 1))
        except (TypeError, ValueError):
            ratio_width, ratio_height = 9, 16
        width, height = (1080, round(1080 * ratio_height / ratio_width)) if ratio_width >= ratio_height else (1080, round(1080 * ratio_height / ratio_width))
        if ratio_width > ratio_height:
            width, height = round(1080 * ratio_width / ratio_height), 1080
        now = datetime.now(timezone.utc).isoformat()
        project = {
            "version": 1,
            "name": canvas_name,
            "createdAt": now,
            "updatedAt": now,
            "aspectRatio": ratio,
            "resolution": "1080P",
            "width": width,
            "height": height,
            "styleKey": "",
            "stylePrompt": "",
            "language": "zh-CN",
            "directorSkill": "",
            "episodeCount": max(1, len(episodes)),
            "episodeSeconds": 90,
            "fps": 30,
            "tts": {"voice": "default", "speed": 1, "language": "zh-CN", "format": "mp3", "sampleRate": 44100, "volume": 0},
            "jianying": {"mode": "episode", "includeCover": True, "includeSubtitles": True, "includeBgm": False, "bgmPath": "", "bgmVolume": 0.18, "coverSeconds": 0.06},
            "pipeline": {"includeSubtitles": True, "includeCover": False, "includeBgm": False, "bgmPath": "", "bgmVolume": 0.18},
            "cover": {"platform": ratio, "fontPath": "C:/Windows/Fonts/msyhbd.ttc", "titleSize": max(48, round(width * 0.095)), "subtitleSize": max(28, round(width * 0.042)), "textPosition": "bottom", "safeArea": 0.12, "outline": 3, "shadow": 1},
        }
        settings_dir = output / ".solodrama"
        settings_dir.mkdir(parents=True, exist_ok=True)
        (settings_dir / "project.json").write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "import-report.json").write_text(json.dumps(state.report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state.report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import a legacy SoloDrama workspace into a new SoloDrama workspace (one-way).")
    parser.add_argument("--source", required=True, help="legacy SoloDrama workspace")
    parser.add_argument("--output", required=True, help="new SoloDrama workspace directory")
    parser.add_argument("--layout", type=Path, default=None, help="optional legacy layout.json")
    parser.add_argument("--pack", type=Path, default=None, help="optional legacy pack directory")
    parser.add_argument("--canvas-name", default="SoloDrama导入", help="canvas JSON basename without .json")
    parser.add_argument("--dry-run", action="store_true", help="scan and report without copying or writing")
    args = parser.parse_args(argv)
    try:
        report = run(Path(args.source), Path(args.output), args.layout, args.pack, args.canvas_name, args.dry_run)
    except Exception as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
