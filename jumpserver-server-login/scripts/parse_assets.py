#!/usr/bin/env python3
"""Parse Jumpserver host list output and match server assets."""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from dataclasses import asdict, dataclass
from typing import Iterable


HEADER_ALIASES = {
    "id": "id",
    "ID": "id",
    "编号": "id",
    "名称": "name",
    "主机名": "name",
    "主机": "name",
    "备注": "remark",
    "地址": "address",
    "ip": "address",
    "IP": "address",
    "平台": "platform",
    "系统": "platform",
}
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


@dataclass
class Asset:
    id: str
    name: str
    address: str
    platform: str
    remark: str = ""


def normalize_cell(value: str) -> str:
    return ANSI_RE.sub("", value).strip().strip("|").strip()


def split_row(line: str) -> list[str]:
    if "|" in line:
        return [normalize_cell(part) for part in line.split("|")]
    return [part for part in re.split(r"\s{2,}", line.strip()) if part]


def looks_like_separator(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    return bool(compact) and set(compact) <= {"-", "+", "|", ":"}


def is_header(cells: Iterable[str]) -> bool:
    canonical = {canonical_header(cell) for cell in cells}
    return "id" in canonical and ("name" in canonical or "address" in canonical)


def canonical_header(cell: str) -> str:
    stripped = cell.strip()
    return HEADER_ALIASES.get(stripped, HEADER_ALIASES.get(stripped.lower(), ""))


def header_map(cells: list[str]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for index, cell in enumerate(cells):
        key = canonical_header(cell)
        if key:
            mapping[index] = key
    return mapping


def parse_footer(text: str) -> dict[str, int | None]:
    footer = {"page": None, "page_size": None, "total_pages": None, "total": None}
    patterns = {
        "page": r"页码\s*[:：]\s*(\d+)",
        "page_size": r"每页行数\s*[:：]\s*(\d+)",
        "total_pages": r"总页数\s*[:：]\s*(\d+)",
        "total": r"总数量\s*[:：]\s*(\d+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            footer[key] = int(match.group(1))
    return footer


def parse_assets(text: str) -> tuple[list[Asset], dict[str, int | None]]:
    assets: list[Asset] = []
    mapping: dict[int, str] | None = None

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or looks_like_separator(stripped):
            continue

        cells = split_row(stripped)
        if not cells:
            continue

        if is_header(cells):
            mapping = header_map(cells)
            continue

        if mapping is None:
            continue

        values = {"id": "", "name": "", "address": "", "platform": "", "remark": ""}
        for index, key in mapping.items():
            if index < len(cells):
                values[key] = cells[index]

        if values["id"] and re.fullmatch(r"\d+", values["id"]):
            assets.append(Asset(**values))

    return assets, parse_footer(text)


def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def match_assets(assets: list[Asset], target: str) -> list[Asset]:
    needle = target.strip()
    if not needle:
        return assets

    if is_ip(needle):
        exact_ip = [asset for asset in assets if asset.address == needle]
        if exact_ip:
            return exact_ip

    exact_name = [
        asset
        for asset in assets
        if asset.name == needle or asset.remark == needle or asset.id == needle
    ]
    if exact_name:
        return exact_name

    lowered = needle.lower()
    return [
        asset
        for asset in assets
        if lowered
        in " ".join(
            [asset.id, asset.name, asset.address, asset.platform, asset.remark]
        ).lower()
    ]


def markdown_table(assets: list[Asset]) -> str:
    lines = [
        "| ID | 名称 | 地址 | 平台 | 备注 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for asset in assets:
        lines.append(
            f"| {asset.id} | {asset.name} | {asset.address} | {asset.platform} | {asset.remark} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse Jumpserver p list output and match host assets."
    )
    parser.add_argument("--target", help="IP, host name, remark, or partial keyword to match")
    parser.add_argument(
        "--format",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format. Defaults to markdown.",
    )
    args = parser.parse_args()

    text = sys.stdin.read()
    assets, footer = parse_assets(text)
    matches = match_assets(assets, args.target or "")
    has_more_pages = bool(
        footer["page"] and footer["total_pages"] and footer["page"] < footer["total_pages"]
    )

    if args.format == "json":
        print(
            json.dumps(
                {
                    "assets": [asdict(asset) for asset in assets],
                    "matches": [asdict(asset) for asset in matches],
                    "footer": footer,
                    "has_more_pages": has_more_pages,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.target:
        print(f"匹配目标: {args.target}")
        print(f"匹配数量: {len(matches)}")
    else:
        print(f"资产数量: {len(assets)}")

    if matches:
        print(markdown_table(matches))
    else:
        print("未匹配到资产。请输入更准确的 IP、名称或备注，或继续翻页收集列表。")

    if has_more_pages:
        print(f"当前第 {footer['page']} 页，共 {footer['total_pages']} 页；如未唯一命中，请在 Jumpserver 输入 n 继续收集下一页。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
