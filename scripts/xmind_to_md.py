#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XMind 功能点大纲 → Markdown 转换器（通用）
支持 content.json（新版 XMind）和 content.xml（旧版）
用法: python scripts/xmind_to_md.py <xmind路径> [--output <输出路径>]
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

MAX_HEADING_DEPTH = 4  # 最多渲染到 H4，更深用缩进列表


# ── Parse ──────────────────────────────────────────────

def parse_xmind(xmind_path: str) -> dict:
    """自动检测并解析 XMind 文件"""
    with zipfile.ZipFile(xmind_path, 'r') as z:
        names = z.namelist()

        if 'content.json' in names:
            return _parse_json(z)
        elif 'content.xml' in names:
            return _parse_xml(z)
        else:
            raise ValueError("XMind 文件中未找到 content.json 或 content.xml")


def _parse_json(z: zipfile.ZipFile) -> dict:
    """解析新版 XMind (content.json)"""
    sheets = json.loads(z.read('content.json').decode('utf-8'))
    sheet = sheets[0]
    root = sheet['rootTopic']
    return {
        'title': root['title'],
        'children': _walk_json_children(root.get('children', {}).get('attached', []))
    }


def _walk_json_children(attached: list) -> list:
    """递归解析 content.json 的子节点"""
    result = []
    for node in attached:
        title = node.get('title', '')
        child_attached = node.get('children', {}).get('attached', [])
        children = _walk_json_children(child_attached) if child_attached else []
        # 跳过 XMind 自动生成的摘要/边界等元节点
        if title in ('', 'summaries', 'boundary'):
            continue
        result.append({'title': title, 'children': children})
    return result


def _parse_xml(z: zipfile.ZipFile) -> dict:
    """解析旧版 XMind (content.xml)"""
    ns = {'x': 'urn:xmind:xmap:xmlns:content:2.0'}
    content = z.read('content.xml').decode('utf-8')
    root_el = ET.fromstring(content)

    sheet = root_el.find('x:sheet', ns)
    root_topic = sheet.find('x:topic', ns)
    title_el = root_topic.find('x:title', ns)
    title = title_el.text.strip() if title_el is not None and title_el.text else ''

    children = _walk_xml_children(root_topic, ns)
    return {'title': title, 'children': children}


def _walk_xml_children(topic, ns: dict) -> list:
    """递归解析 content.xml 的子节点"""
    result = []
    children_el = topic.find('x:children', ns)
    if children_el is None:
        return result

    attached = children_el.find('x:topics', ns)
    if attached is None:
        return result

    for child in attached.findall('x:topic', ns):
        title_el = child.find('x:title', ns)
        title = title_el.text.strip() if title_el is not None and title_el.text else ''
        sub_children = _walk_xml_children(child, ns)
        result.append({'title': title, 'children': sub_children})

    return result


# ── Render ──────────────────────────────────────────────

def to_markdown(data: dict, source_path: str = '') -> str:
    """将解析结果渲染为 Markdown"""
    lines = []

    # 标题：优先用文件名，XMind 根节点通常是 "中心主题"
    title = data['title']
    if title in ('中心主题', 'Central Topic', 'Sheet 1'):
        title = Path(source_path).stem if source_path else title
    lines.append(f"# {title}")
    lines.append('')

    # 目录
    toc = []
    _collect_toc(data['children'], toc, 0)
    if toc:
        lines.append('## 目录')
        lines.append('')
        for indent, text in toc:
            prefix = '  ' * indent + '-'
            lines.append(f"{prefix} {text}")
        lines.append('')

    # 正文
    _render_children(data['children'], lines, depth=2)
    return '\n'.join(lines)


def _collect_toc(children: list, toc: list, indent: int):
    """收集目录条目（只到 H4 深度）"""
    for node in children:
        title = node['title']
        if not title:
            continue
        if node['children']:
            toc.append((indent, title))
            if indent < MAX_HEADING_DEPTH - 2:
                _collect_toc(node['children'], toc, indent + 1)


def _render_children(children: list, lines: list, depth: int):
    """递归渲染子节点"""
    for node in children:
        title = node['title']
        if not title:
            continue

        kids = node['children']

        if kids and depth <= MAX_HEADING_DEPTH:
            # 标题深度内 → 用 heading
            heading = '#' * depth
            lines.append(f'{heading} {title}')
            lines.append('')
            _render_children(kids, lines, depth + 1)
        elif kids:
            # 超过最大标题深度 → 用加粗 + 缩进列表
            indent = '  ' * (depth - MAX_HEADING_DEPTH - 1)
            lines.append(f'{indent}- **{title}**')
            _render_children(kids, lines, depth + 1)
        else:
            # 叶子节点 → 列表项
            base_indent = max(depth - 2, 0)
            indent = '  ' * base_indent
            lines.append(f'{indent}- {title}')

    # 叶子列表后空一行
    if children and all(not n['children'] for n in children):
        lines.append('')


# ── Main ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='将 XMind 功能点大纲文件转换为 Markdown'
    )
    parser.add_argument('xmind', help='XMind 文件路径')
    parser.add_argument('--output', '-o', help='输出 Markdown 路径（默认与输入同目录同名 .md）')
    args = parser.parse_args()

    xmind_path = Path(args.xmind)
    if not xmind_path.exists():
        print(f'错误：文件不存在 - {args.xmind}', file=sys.stderr)
        sys.exit(1)

    print(f'解析 XMind: {xmind_path}')
    data = parse_xmind(str(xmind_path))
    print(f'  标题: {data["title"]}')

    md = to_markdown(data, str(xmind_path))

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = xmind_path.with_suffix('.md')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(md)
    print(f'已生成 Markdown: {out_path} ({len(md)} 字符)')


if __name__ == '__main__':
    main()
