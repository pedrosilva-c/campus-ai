"""Documents the assistant delivers: Word (.docx, Office Open XML written directly) and Markdown (.md).

No dependency: a .docx is a zip with a few XML parts; this writes the minimum Word needs (headings, paragraphs,
bullets, simple tables). Text is XML-escaped; nothing from outside is ever interpreted as markup.
Files are written only inside the delivery folder and never overwrite an existing file.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from .store import fold


@dataclass
class Document:
    title: str
    blocks: list = field(default_factory=list)      # ('h1'|'h2'|'p'|'li'|'table', payload)

    def heading(self, text, level=2):
        self.blocks.append((f'h{level}', str(text)))
        return self

    def paragraph(self, text):
        self.blocks.append(('p', str(text)))
        return self

    def bullets(self, items):
        for item in items:
            self.blocks.append(('li', str(item)))
        return self

    def table(self, header, rows):
        self.blocks.append(('table', ([str(h) for h in header], [[str(c) for c in r] for r in rows])))
        return self


def slug(text: str, limit: int = 60) -> str:
    value = re.sub(r'[^a-z0-9]+', '-', fold(text)).strip('-')
    return value[:limit].strip('-') or 'documento'


def unique_path(folder: Path, stem: str, suffix: str) -> Path:
    candidate = folder / f'{stem}{suffix}'
    n = 2
    while candidate.exists():
        candidate = folder / f'{stem}-{n}{suffix}'
        n += 1
    return candidate


# --- Markdown ------------------------------------------------------------------------------------------------------
def to_markdown(doc: Document) -> str:
    out = [f'# {doc.title}', '']
    previous = ''
    for kind, payload in doc.blocks:
        if previous == 'li' and kind != 'li':
            out.append('')                                  # a list ends with a blank line before the next block
        previous = kind
        if kind in ('h1', 'h2', 'h3'):
            out += ['#' * (int(kind[1]) + 1) + ' ' + payload, '']
        elif kind == 'p':
            out += [payload, '']
        elif kind == 'li':
            out.append(f'- {payload}')
        elif kind == 'table':
            header, rows = payload
            cell = lambda value: value.replace('|', '\\|').replace('\n', ' ')      # noqa: E731
            out += ['', '| ' + ' | '.join(map(cell, header)) + ' |', '|' + ' --- |' * len(header)]
            out += ['| ' + ' | '.join(map(cell, row)) + ' |' for row in rows]
            out.append('')
    return '\n'.join(out).replace('\n\n\n', '\n\n').rstrip() + '\n'


# --- Word (.docx) --------------------------------------------------------------------------------------------------
_W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
_CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                  '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                  '<Default Extension="xml" ContentType="application/xml"/>'
                  '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                  'wordprocessingml.document.main+xml"/>'
                  '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.'
                  'wordprocessingml.styles+xml"/>'
                  '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.'
                  'core-properties+xml"/></Types>')
_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
         '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
         'officeDocument" Target="word/document.xml"/>'
         '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/'
         'core-properties" Target="docProps/core.xml"/></Relationships>')
_DOC_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
             'Target="styles.xml"/></Relationships>')


def _style(style_id, name, size, bold=False, based='Normal'):
    return (f'<w:style w:type="paragraph" w:styleId="{style_id}"><w:name w:val="{name}"/><w:basedOn w:val="{based}"/>'
            f'<w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:before="240" w:after="120"/></w:pPr>'
            f'<w:rPr>{"<w:b/>" if bold else ""}<w:sz w:val="{size}"/></w:rPr></w:style>')


_STYLES = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="{_W}">'
           '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>'
           '<w:sz w:val="22"/><w:lang w:val="pt-BR"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr>'
           '<w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>'
           '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>'
           + _style('Title', 'Title', 40, True) + _style('Heading1', 'heading 1', 32, True)
           + _style('Heading2', 'heading 2', 26, True) + _style('Heading3', 'heading 3', 24, True)
           + '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/>'
           '<w:pPr><w:ind w:left="360" w:hanging="360"/></w:pPr></w:style>'
           '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr><w:tblBorders>'
           + ''.join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
                     for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'))
           + '</w:tblBorders></w:tblPr></w:style></w:styles>')


_CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def _run(text, bold=False):
    parts = _CONTROL.sub('', str(text)).split('\n')
    inner = '<w:br/>'.join(f'<w:t xml:space="preserve">{escape(p)}</w:t>' for p in parts)
    return f'<w:r>{"<w:rPr><w:b/></w:rPr>" if bold else ""}{inner}</w:r>'


def _para(text, style=None, bold=False):
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ''
    return f'<w:p>{props}{_run(text, bold)}</w:p>'


def _table(header, rows):
    def cell(text, bold=False):
        return f'<w:tc><w:tcPr><w:tcW w:w="0" w:type="auto"/></w:tcPr>{_para(text, bold=bold)}</w:tc>'
    body = '<w:tr>' + ''.join(cell(h, True) for h in header) + '</w:tr>'
    body += ''.join('<w:tr>' + ''.join(cell(c) for c in row) + '</w:tr>' for row in rows)
    return (f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/></w:tblPr>'
            f'<w:tblGrid>{"<w:gridCol/>" * len(header)}</w:tblGrid>{body}</w:tbl><w:p/>')


def to_docx_bytes(doc: Document, *, when: datetime | None = None) -> bytes:
    import io
    parts = [_para(doc.title, 'Title')]
    for kind, payload in doc.blocks:
        if kind in ('h1', 'h2', 'h3'):
            parts.append(_para(payload, f'Heading{kind[1]}'))
        elif kind == 'p':
            parts.append(_para(payload))
        elif kind == 'li':
            parts.append(_para('•\t' + payload, 'ListBullet'))
        elif kind == 'table':
            parts.append(_table(*payload))
    body = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{_W}"><w:body>'
            + ''.join(parts) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" '
            'w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
    stamp = (when or datetime.now(timezone.utc)).strftime('%Y-%m-%dT%H:%M:%SZ')
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(doc.title)}</dc:title><dc:creator>Campus AI (Jarvis)</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created></cp:coreProperties>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', _CONTENT_TYPES)
        z.writestr('_rels/.rels', _RELS)
        z.writestr('word/_rels/document.xml.rels', _DOC_RELS)
        z.writestr('word/document.xml', body)
        z.writestr('word/styles.xml', _STYLES)
        z.writestr('docProps/core.xml', core)
    return buffer.getvalue()


def write(doc: Document, folder: Path, stem: str) -> list[Path]:
    """Writes <stem>.docx and <stem>.md in ``folder`` (created if needed). Returns both paths."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    docx = unique_path(folder, stem, '.docx')
    md = docx.with_suffix('.md')
    if md.exists():
        md = unique_path(folder, docx.stem, '.md')
    docx.write_bytes(to_docx_bytes(doc))
    md.write_text(to_markdown(doc), encoding='utf-8')
    return [docx, md]
