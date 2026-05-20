import streamlit as st
import streamlit.components.v1 as components
import json
import re
import base64
import fitz  # PyMuPDF

try:
    from code_editor import code_editor
    HAS_CODE_EDITOR = True
except ImportError:
    HAS_CODE_EDITOR = False

st.set_page_config(
    page_title="LaTeX Question Preview",
    page_icon="🔍",
    layout="wide"
)

# ================================================================
# PREVIEW RENDER HELPERS  (copied from perfectcode.py — no import
# to avoid page_config conflict)
# ================================================================

_LADDER_DIVISOR_RE = re.compile(r'^\s*\d+\s*\|')
_LADDER_SEP_RE     = re.compile(r'^\s*\|[_\s]+$')
_LADDER_EMPTY_DIV  = re.compile(r'^\s*\|')
_LADDER_FINAL_RE   = re.compile(r'^\s+\d[\d\s]+$')
_LADDER_ROW_PARSE  = re.compile(r'^(\s*\d*)\s*\|\s*(.+)$')


def _lcm_ladder_to_html(ladder_lines: list) -> str:
    rows, final_nums = [], None
    for line in ladder_lines:
        stripped = line.strip()
        if _LADDER_SEP_RE.match(stripped):
            continue
        m = _LADDER_ROW_PARSE.match(stripped)
        if m:
            rows.append((m.group(1).strip(), m.group(2)))
        elif _LADDER_FINAL_RE.match(line):
            final_nums = line.strip()
    if not rows:
        return ''
    VL = '2px solid #111'
    HL = '1.5px solid #111'
    S_D = (f'border:none;border-right:{VL};border-bottom:{HL};'
           f'text-align:right;padding:3px 6px 3px 4px;vertical-align:middle;'
           f'font-weight:bold;min-width:20px')
    S_N = (f'border:none;border-bottom:{HL};'
           f'padding:3px 10px 3px 8px;white-space:pre;vertical-align:middle')
    tbl = ('<table class="lcm-ladder-t" style="border-collapse:collapse;'
           'font-family:\'Courier New\',Courier,monospace;font-size:14px;'
           'line-height:1.9;margin:8px 0">')
    for div, nums in rows:
        de = div.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        ne = nums.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        tbl += f'<tr><td style="{S_D}">{de}</td><td style="{S_N}">{ne}</td></tr>'
    if final_nums is not None:
        fe = final_nums.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        SF_D = 'border:none;padding:3px 6px 3px 4px;min-width:20px'
        SF_N = 'border:none;padding:3px 10px 3px 8px;white-space:pre;vertical-align:middle'
        tbl += f'<tr><td style="{SF_D}"></td><td style="{SF_N}">{fe}</td></tr>'
    tbl += '</table>'
    return tbl


def _md_table_to_html(text: str) -> str:
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    lines = text.split('\n')
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if '|' in line and stripped.startswith('|') and not _LADDER_SEP_RE.match(stripped):
            table_lines = []
            while i < len(lines) and '|' in lines[i] and lines[i].strip().startswith('|'):
                table_lines.append(lines[i])
                i += 1
            rows = [r for r in table_lines if not re.match(r'^\s*\|[\s\-|:]+\|\s*$', r)]
            if rows:
                html = '<table class="qtable" style="border-collapse:collapse;margin:8px 0">'
                for ri, row in enumerate(rows):
                    cells = [c.strip() for c in row.strip().strip('|').split('|')]
                    if ri == 0:
                        html += ('<tr>' + ''.join(
                            f'<th style="border:1px solid #333;padding:5px 10px;'
                            f'background:#dbeafe;font-weight:bold;text-align:center">{c}</th>'
                            for c in cells) + '</tr>')
                    else:
                        html += ('<tr>' + ''.join(
                            f'<td style="border:1px solid #333;padding:5px 10px;'
                            f'text-align:left;vertical-align:middle">{c}</td>'
                            for c in cells) + '</tr>')
                html += '</table>'
                out.append(html)
            continue
        if _LADDER_DIVISOR_RE.match(stripped):
            ladder_lines = []
            while i < len(lines):
                s = lines[i]
                ss = s.strip()
                if (_LADDER_DIVISOR_RE.match(ss) or _LADDER_SEP_RE.match(ss) or
                        _LADDER_EMPTY_DIV.match(ss) or
                        (ladder_lines and _LADDER_FINAL_RE.match(s))):
                    ladder_lines.append(s)
                    i += 1
                elif ss == '' and ladder_lines:
                    break
                else:
                    break
            if len(ladder_lines) >= 2:
                out.append(_lcm_ladder_to_html(ladder_lines))
            else:
                out.extend(ladder_lines)
            continue
        out.append(line)
        i += 1
    return '\n'.join(out)


def _normalize_html_table(table_html: str) -> str:
    head = table_html[:120].lower()
    if 'lcm-ladder-t' in head:
        return table_html
    if 'class=' not in head:
        return table_html.replace('<table', '<table class="ltable"', 1)
    if 'qtable' not in head and 'ltable' not in head and 'lcm-table' not in head:
        return re.sub(r'class="', 'class="ltable ', table_html, count=1, flags=re.IGNORECASE)
    return table_html


_KEEP_RE = re.compile(
    r'(<img\b[^>]*?>'
    r'|<table\b[^>]*?>.*?</table\s*>'
    r'|<pre\b[^>]*?>.*?</pre\s*>)',
    re.IGNORECASE | re.DOTALL
)


def _clean_for_html(text: str) -> str:
    if not text or not isinstance(text, str):
        return ''
    text = _md_table_to_html(text)
    segments = _KEEP_RE.split(text)
    result = []
    for seg in segments:
        if _KEEP_RE.match(seg):
            if seg.lower().startswith('<table'):
                seg = _normalize_html_table(seg)
            result.append(seg)
        else:
            s = seg
            s = re.sub(r'<br\s*/?>', '\n', s, flags=re.IGNORECASE)
            s = re.sub(r'<[^>]+>', '', s)
            s = re.sub(r'\\\\\((.+?)\\\\\)', r'\\(\1\\)', s, flags=re.DOTALL)
            s = re.sub(r'\\\\\[(.+?)\\\\\]', r'\\[\1\\]', s, flags=re.DOTALL)
            s = s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            s = s.replace('\n', '<br>')
            result.append(s)
    return ''.join(result)


def _build_preview_html(questions: list) -> str:
    if not questions:
        return '<p style="color:#888;padding:16px;font-family:sans-serif">JSON paste karo — preview yahan aayega…</p>'
    body_parts = []
    for q in questions:
        qid      = q.get('questionid', '?')
        qtxt     = _clean_for_html(str(q.get('question', '')))
        opts_html = ''
        for i in range(1, 5):
            opt = q.get(f'option{i}', '')
            if opt:
                lbl = chr(64 + i)
                opts_html += (
                    f'<div class="opt">'
                    f'<span class="lbl">({lbl})</span>&nbsp;{_clean_for_html(str(opt))}'
                    f'</div>'
                )
        ans = q.get('Answer', '')
        exp = q.get('Explanation', '')
        ans_html = f'<div class="ans">&#x2705; <b>Answer:</b> {ans}</div>' if ans else ''
        exp_html = (
            f'<div class="exp">&#x1F4A1; <b>Explanation:</b> {_clean_for_html(str(exp))}</div>'
            if exp else ''
        )
        meta_parts = []
        for key in ('course', 'subjectname', 'chapter', 'difficulty', 'marks'):
            val = q.get(key, '')
            if val:
                meta_parts.append(f'<span class="mtag">{key}: {val}</span>')
        meta_html = f'<div class="meta">{"&nbsp;&nbsp;".join(meta_parts)}</div>' if meta_parts else ''
        body_parts.append(
            f'<div class="qblock">'
            f'{meta_html}'
            f'<div class="qtext"><b>Q{qid}.</b>&nbsp;{qtxt}</div>'
            f'<div class="opts">{opts_html}</div>'
            f'{ans_html}{exp_html}'
            f'</div>'
        )
    body = '\n'.join(body_parts)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">\n'
        '<script>\n'
        'window.MathJax = {\n'
        '  tex: {\n'
        '    inlineMath: [["\\\\(","\\\\)"]],\n'
        '    displayMath: [["\\\\[","\\\\]"]],\n'
        '    processEscapes: true\n'
        '  },\n'
        '  options: { skipHtmlTags: ["script","noscript","style","textarea"] }\n'
        '};\n'
        '</script>\n'
        '<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>\n'
        '<style>\n'
        '::-webkit-scrollbar{width:10px;height:10px}'
        '::-webkit-scrollbar-track{background:#f0f4ff;border-radius:4px}'
        '::-webkit-scrollbar-thumb{background:#0078d4;border-radius:4px;border:2px solid #f0f4ff}'
        '::-webkit-scrollbar-thumb:hover{background:#1a9fd4}'
        '::-webkit-scrollbar-corner{background:#f0f4ff}\n'
        'body{font-family:"Times New Roman",serif;font-size:14px;line-height:1.8;'
        'color:#111;background:#fff;padding:12px;margin:0}\n'
        '.qblock{margin-bottom:20px;padding:10px 14px;border-left:3px solid #2563eb;'
        'background:#f8fafc;border-radius:3px}\n'
        '.qtext{margin-bottom:8px}.opts{margin-left:18px}.opt{margin:4px 0}\n'
        '.lbl{font-weight:bold;color:#374151}\n'
        '.ans{margin-top:8px;color:#15803d;font-size:13px}\n'
        '.exp{margin-top:6px;color:#374151;font-size:13px}\n'
        '.meta{margin-top:6px;font-size:11px;color:#6b7280}\n'
        '.mtag{background:#e5e7eb;border-radius:3px;padding:1px 5px;margin-right:4px}\n'
        'table{border-collapse:collapse;margin:8px 0;max-width:100%;font-size:13px;'
        'font-family:"Times New Roman",serif}\n'
        'table td,table th{border:1px solid #444;padding:5px 10px;vertical-align:middle;'
        'text-align:center}\n'
        'table th{background:#dbeafe;font-weight:bold;color:#1e3a8a}\n'
        'table tr:nth-child(even) td{background:#f8fafc}\n'
        'table.qtable td,table.qtable th,table.ltable td,table.ltable th{text-align:left}\n'
        'table.lcm-ladder-t{border-collapse:collapse}\n'
        'img{max-width:100%;height:auto;display:block;margin:6px auto;border-radius:2px}\n'
        'mjx-container[display="true"]{display:block;margin:6px 0;overflow-x:auto}\n'
        '.MathJax{font-size:1em!important}\n'
        '</style></head><body>\n'
        + body +
        '\n</body></html>'
    )


# ================================================================
# PDF PAGE RENDERER
# ================================================================

def _render_pdf_html(pdf_bytes: bytes, height_px: int = 200, zoom: float = 1.5) -> str:
    """Render all PDF pages as PNG images inside a scrollable dark container."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        imgs = []
        for i in range(len(doc)):
            pix = doc[i].get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB)
            b64 = base64.b64encode(pix.tobytes("png")).decode()
            imgs.append(
                f'<div style="margin-bottom:6px;text-align:center;color:#555;font-size:11px;'
                f'font-family:Consolas,monospace">Page {i+1}</div>'
                f'<img src="data:image/png;base64,{b64}" '
                f'style="width:100%;border:1px solid #3c3c3c;border-radius:2px;display:block"/>'
            )
        doc.close()
        body = ''.join(imgs) if imgs else '<p style="color:#555;padding:20px;text-align:center">PDF empty</p>'
    except Exception as e:
        body = f'<p style="color:#f87171;padding:16px">PDF render error: {e}</p>'

    _sb_css = (
        "<style>"
        "::-webkit-scrollbar{width:10px;height:10px}"
        "::-webkit-scrollbar-track{background:#1e1e1e;border-radius:4px}"
        "::-webkit-scrollbar-thumb{background:#0078d4;border-radius:4px;border:2px solid #1e1e1e}"
        "::-webkit-scrollbar-thumb:hover{background:#1a9fd4}"
        "::-webkit-scrollbar-corner{background:#1e1e1e}"
        "</style>"
    )
    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">{_sb_css}</head><body style="margin:0;padding:0;background:#1e1e1e">'
        f'<div style="height:{height_px}px;overflow-y:auto;overflow-x:hidden;'
        f'background:#1e1e1e;padding:8px;border-radius:4px;'
        f'border:1px solid #3c3c3c;box-sizing:border-box">'
        f'{body}'
        f'</div></body></html>'
    )


# ================================================================
# UI
# ================================================================

st.markdown(
    "<h2 style='margin-bottom:4px'>🔍 LaTeX Question Preview</h2>"
    "<p style='color:#6b7280;margin-top:0'>JSON paste karo → Live LaTeX preview dekho</p>",
    unsafe_allow_html=True,
)
st.markdown("---")

# ── VS Code dark theme CSS + visible scrollbars ───────────────────
st.markdown("""
<style>
/* ── Textarea dark theme ── */
div[data-testid="stTextArea"] textarea {
    background-color: #1e1e1e !important;
    color: #d4d4d4 !important;
    font-family: 'Cascadia Code', 'Fira Code', Consolas, 'Courier New', monospace !important;
    font-size: 13px !important;
    line-height: 1.6 !important;
    border: 1px solid #3c3c3c !important;
    border-radius: 4px !important;
    caret-color: #d4d4d4 !important;
    padding: 10px 12px !important;
    resize: none !important;
    overflow-x: scroll !important;
    overflow-y: scroll !important;
    white-space: pre !important;
}
div[data-testid="stTextArea"] textarea:focus {
    border-color: #007acc !important;
    box-shadow: 0 0 0 1px #007acc !important;
    outline: none !important;
}
div[data-testid="stTextArea"] textarea::placeholder {
    color: #555 !important;
}
div[data-testid="stTextArea"] label {
    color: #9cdcfe !important;
    font-family: Consolas, monospace !important;
    font-size: 12px !important;
}
/* ── Scrollbars: white, always visible ── */
div[data-testid="stTextArea"] textarea {
    overflow-x: scroll !important;
    overflow-y: scroll !important;
}
div[data-testid="stTextArea"] textarea::-webkit-scrollbar {
    width: 12px !important;
    height: 12px !important;
    display: block !important;
}
div[data-testid="stTextArea"] textarea::-webkit-scrollbar-track {
    background: #2d2d2d !important;
    border-radius: 6px !important;
}
div[data-testid="stTextArea"] textarea::-webkit-scrollbar-thumb {
    background: #ffffff !important;
    border-radius: 6px !important;
    border: 2px solid #2d2d2d !important;
    min-height: 30px !important;
    min-width: 30px !important;
}
div[data-testid="stTextArea"] textarea::-webkit-scrollbar-thumb:hover {
    background: #cccccc !important;
}
div[data-testid="stTextArea"] textarea::-webkit-scrollbar-corner {
    background: #2d2d2d !important;
}
/* ── Tag wrapper around JSON editor ── */
.json-editor-wrap {
    border: 1px solid #3c3c3c;
    border-radius: 6px;
    overflow: hidden;
    background: #1e1e1e;
    margin-bottom: 4px;
}
.json-editor-tag {
    background: #252526;
    border-bottom: 1px solid #3c3c3c;
    padding: 4px 12px;
    font-family: Consolas, monospace;
    font-size: 12px;
    color: #9cdcfe;
    display: flex;
    align-items: center;
    gap: 6px;
    user-select: none;
}
.json-editor-tag .dot { width:10px;height:10px;border-radius:50%;display:inline-block }
</style>
""", unsafe_allow_html=True)

# ── Session state init ────────────────────────────────────────────
if "json_input" not in st.session_state:
    st.session_state["json_input"] = ""
if "pdf_bytes" not in st.session_state:
    st.session_state["pdf_bytes"] = None
if "pdf_name" not in st.session_state:
    st.session_state["pdf_name"] = ""

# Apply any pending value BEFORE widget renders (Streamlit rule)
if "_json_next" in st.session_state:
    st.session_state["json_input"] = st.session_state.pop("_json_next")

# ══════════════════════════════════════════════════════════════════
# PANEL RESIZE CONTROLS
# ══════════════════════════════════════════════════════════════════
st.markdown(
    "<div style='background:#1e1e1e;border:1px solid #3c3c3c;border-radius:6px;"
    "padding:6px 14px 2px 14px;margin-bottom:6px'>"
    "<span style='color:#9cdcfe;font-family:Consolas,monospace;font-size:11px'>"
    "⇔ Panel Width Resize</span></div>",
    unsafe_allow_html=True,
)
_rc1, _rc2, _rc3 = st.columns(3)
w_pdf = _rc1.slider(
    "📄 PDF", min_value=1, max_value=6, value=2, step=1, key="w_pdf"
)
w_prev = _rc2.slider(
    "👁️ Preview", min_value=1, max_value=6, value=2, step=1, key="w_prev"
)
w_json = _rc3.slider(
    "{ } JSON", min_value=1, max_value=6, value=2, step=1, key="w_json"
)

# ══════════════════════════════════════════════════════════════════
# THREE COLUMNS  —  PDF  |  Preview  |  JSON  (dynamic widths)
# ══════════════════════════════════════════════════════════════════
col_pdf, col_prev, col_json = st.columns([w_pdf, w_prev, w_json], gap="small")

# ── COLUMN 1: PDF viewer ──────────────────────────────────────────
with col_pdf:
    st.subheader("📄 PDF")
    pdf_up = st.file_uploader(
        "PDF upload karo", type=["pdf"],
        label_visibility="collapsed", key="pdf_uploader",
    )
    if pdf_up:
        st.session_state["pdf_bytes"] = pdf_up.read()
        st.session_state["pdf_name"] = pdf_up.name

    if st.session_state["pdf_bytes"]:
        components.html(
            _render_pdf_html(st.session_state["pdf_bytes"], height_px=640),
            height=650,
        )
        st.caption(f"📄 {st.session_state['pdf_name']}")
    else:
        st.markdown(
            "<div style='background:#1e1e1e;border:1px dashed #3c3c3c;"
            "border-radius:4px;height:640px;display:flex;align-items:center;"
            "justify-content:center;color:#555;font-family:Consolas,monospace;"
            "font-size:12px;text-align:center'>"
            "📄 PDF upload karo</div>",
            unsafe_allow_html=True,
        )

# ── COLUMN 2: LaTeX preview ───────────────────────────────────────
# questions will be set by col_json block — need to parse first
# so we parse JSON before rendering preview
questions = []
error_msg = ""

# pre-parse from session state so preview renders correctly on rerun
_raw_pre = (st.session_state.get("json_input") or "").lstrip("﻿").strip()
if _raw_pre:
    try:
        _p = json.loads(_raw_pre)
        questions = [_p] if isinstance(_p, dict) else (_p if isinstance(_p, list) else [])
    except Exception:
        pass

with col_prev:
    st.subheader("👁️ Preview")
    preview_html = _build_preview_html(questions)
    components.html(preview_html, height=650, scrolling=True)
    if questions:
        st.download_button(
            label="⬇️ HTML download",
            data=preview_html,
            file_name="preview.html",
            mime="text/html",
            use_container_width=True,
        )

# ── COLUMN 3: JSON editor ─────────────────────────────────────────
with col_json:
    st.subheader("{ } JSON")

    uploaded = st.file_uploader(
        "JSON upload karo", type=["json"],
        label_visibility="collapsed", key="json_uploader",
    )
    if uploaded:
        try:
            raw_text = uploaded.read().decode("utf-8").lstrip("﻿")
            parsed_upload = json.loads(raw_text)
            st.session_state["_json_next"] = json.dumps(parsed_upload, ensure_ascii=False, indent=2)
        except Exception:
            st.session_state["_json_next"] = uploaded.getvalue().decode("utf-8", errors="replace")
        st.rerun()

    if HAS_CODE_EDITOR:
        # ── VS Code-like editor with fold/expand ─────────────────
        _BTNS = [
            {
                "name": "Format JSON",
                "feather": "Code",
                "primary": True,
                "hasText": True,
                "commands": ["selectall", "jsonBeautify"],
                "style": {"bottom": "0.5rem", "right": "0.5rem"},
            },
            {
                "name": "Copy",
                "feather": "Copy",
                "hasText": True,
                "commands": ["copyAll"],
                "style": {"bottom": "0.5rem", "right": "7rem"},
            },
        ]
        resp = code_editor(
            st.session_state.get("json_input", ""),
            lang="json",
            theme="vs-dark",
            height=[20, 32],          # max 32 lines → scrollbar appears after that
            options={
                "wrap": False,
                "tabSize": 2,
                "showPrintMargin": False,
                "scrollPastEnd": 0.1,
                "hScrollBarAlwaysVisible": True,
                "vScrollBarAlwaysVisible": True,
            },
            props={"style": {"overflow": "auto"}},
            buttons=_BTNS,
            key="code_editor_json",
        )
        # code_editor returns new text when user submits (Ctrl+Enter or button)
        if resp.get("type") == "submit" and resp.get("text"):
            st.session_state["_json_next"] = resp["text"]
            st.rerun()
        json_text = resp.get("text") or st.session_state.get("json_input", "")

    else:
        # ── Tag wrapper header ────────────────────────────────────
        st.markdown(
            "<div class='json-editor-wrap'>"
            "<div class='json-editor-tag'>"
            "<span class='dot' style='background:#ff5f57'></span>"
            "<span class='dot' style='background:#febc2e'></span>"
            "<span class='dot' style='background:#28c840'></span>"
            "&nbsp;&nbsp;{ }&nbsp;<b>data.json</b>"
            "</div></div>",
            unsafe_allow_html=True,
        )
        json_text = st.text_area(
            "JSON Input",
            height=520,
            placeholder='[\n  {\n    "questionid": "1",\n    "question": "...",\n    "Answer": "1"\n  }\n]',
            key="json_input",
            label_visibility="collapsed",
        )

    c_status, c_btn = st.columns([3, 1])
    with c_btn:
        if st.button("🗑️ Clear", use_container_width=True):
            st.session_state["_json_next"] = ""
            st.rerun()

    raw = (json_text or "").lstrip("﻿").strip()
    questions_live = []
    err = ""
    if raw:
        try:
            p = json.loads(raw)
            questions_live = [p] if isinstance(p, dict) else (p if isinstance(p, list) else [])
            if questions_live:
                pretty = json.dumps(
                    questions_live if len(questions_live) > 1 else questions_live[0],
                    ensure_ascii=False, indent=2
                )
                if not HAS_CODE_EDITOR and pretty != raw:
                    st.session_state["_json_next"] = pretty
                    st.rerun()
        except json.JSONDecodeError as e:
            err = f"Parse error: {e}"

    with c_status:
        if err:
            st.error(err)
        elif questions_live:
            st.success(f"✅ {len(questions_live)} question(s)")
