"""Native PowerPoint equations (OMML inside a14:m, as Insert > Equation writes them) for python-pptx text boxes.
Build expressions with the small helpers below (each returns an OMML fragment string), then eq_box() puts one
equation per paragraph into a text box. Letters are math italic by default; t() with plain=True is upright text
(words, Chinese, function names)."""
from xml.sax.saxutils import escape

from lxml import etree
from pptx.util import Inches, Pt

NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" '
      'xmlns:a14="http://schemas.microsoft.com/office/drawing/2010/main" '
      'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"')
SZ = 2000          # default size in 1/100 pt; eq_box sets it per box
_size = [SZ]
_color = ['1F2A30']


def t(s, plain=False, bold=False, color=None):
    rpr = '<m:rPr><m:sty m:val="{}"/></m:rPr>'.format('b' if bold else 'p') if (plain or bold) else ''
    col = color or _color[0]
    return (f'<m:r>{rpr}<a:rPr lang="zh-TW" sz="{_size[0]}" b="{1 if bold else 0}"><a:solidFill><a:srgbClr val="{col}"/></a:solidFill>'
            f'<a:latin typeface="Cambria Math"/><a:ea typeface="Microsoft JhengHei"/><a:cs typeface="Cambria Math"/></a:rPr>'
            f'<m:t xml:space="preserve">{escape(s)}</m:t></m:r>')


def w(s, **k):                       # upright word / Chinese
    return t(s, plain=True, **k)


def cat(*xs):
    return ''.join(xs)


def frac(num, den):
    return f'<m:f><m:num>{num}</m:num><m:den>{den}</m:den></m:f>'


def sub(base, s):
    return f'<m:sSub><m:e>{base}</m:e><m:sub>{s}</m:sub></m:sSub>'


def sup(base, s):
    return f'<m:sSup><m:e>{base}</m:e><m:sup>{s}</m:sup></m:sSup>'


def subsup(base, s, p):
    return f'<m:sSubSup><m:e>{base}</m:e><m:sub>{s}</m:sub><m:sup>{p}</m:sup></m:sSubSup>'


def nary(op, lo, hi, body):
    hide = '' if hi else '<m:supHide m:val="1"/>'
    hide += '' if lo else '<m:subHide m:val="1"/>'
    return (f'<m:nary><m:naryPr><m:chr m:val="{op}"/><m:limLoc m:val="undOvr"/>{hide}</m:naryPr>'
            f'<m:sub>{lo}</m:sub><m:sup>{hi}</m:sup><m:e>{body}</m:e></m:nary>')


def sum_(lo, hi, body):
    return nary('∑', lo, hi, body)


def rad(body):
    return f'<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/><m:e>{body}</m:e></m:rad>'


def par(body, l='(', r=')'):
    return f'<m:d><m:dPr><m:begChr m:val="{escape(l)}"/><m:endChr m:val="{escape(r)}"/></m:dPr><m:e>{body}</m:e></m:d>'


def bar(body):
    return f'<m:bar><m:barPr><m:pos m:val="top"/></m:barPr><m:e>{body}</m:e></m:bar>'


def hat(body):
    return f'<m:acc><m:accPr><m:chr m:val="&#770;"/></m:accPr><m:e>{body}</m:e></m:acc>'


def lim_low(name, lim, arg=''):      # e.g. argmax under c, applied to arg
    return f'<m:func><m:fName><m:limLow><m:e>{w(name)}</m:e><m:lim>{lim}</m:lim></m:limLow></m:fName><m:e>{arg}</m:e></m:func>'


def fn(name, arg):
    return f'<m:func><m:fName>{w(name)}</m:fName><m:e>{arg}</m:e></m:func>'


def cases(*rows):                    # left brace with one row per case
    eqarr = ''.join(f'<m:e>{r}</m:e>' for r in rows)
    return f'<m:d><m:dPr><m:begChr m:val="{{"/><m:endChr m:val=""/></m:dPr><m:e><m:eqArr>{eqarr}</m:eqArr></m:e></m:d>'


def _para(omml, fallback, align):
    return (f'<a:p {NS}><a:pPr algn="{align}"><a:spcAft><a:spcPts val="600"/></a:spcAft></a:pPr>'
            f'<mc:AlternateContent><mc:Choice Requires="a14"><a14:m><m:oMathPara><m:oMathParaPr><m:jc m:val="{"left" if align == "l" else "centerGroup"}"/></m:oMathParaPr>'
            f'<m:oMath>{omml}</m:oMath></m:oMathPara></a14:m></mc:Choice>'
            f'<mc:Fallback><a:r><a:rPr lang="en-US" sz="{_size[0]}"/><a:t>{escape(fallback)}</a:t></a:r></mc:Fallback></mc:AlternateContent></a:p>')


def _text_para(s, sz, color, bold, align):
    return (f'<a:p {NS}><a:pPr algn="{align}"><a:spcBef><a:spcPts val="300"/></a:spcBef><a:spcAft><a:spcPts val="200"/></a:spcAft></a:pPr>'
            f'<a:r><a:rPr lang="zh-TW" sz="{sz}" b="{1 if bold else 0}"><a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
            f'<a:latin typeface="Microsoft JhengHei"/><a:ea typeface="Microsoft JhengHei"/></a:rPr><a:t>{escape(s)}</a:t></a:r></a:p>')


def eq_box(slide, x, y, wdt, h, items, size=20, align='l', label_color='5B6770', color='1F2A30'):
    """items: list of ('eq', omml, fallback) or ('txt', text[, bold]) -> one paragraph each"""
    _size[0], _color[0] = int(size * 100), color
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(wdt), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    body = tf._txBody
    for p in list(body.findall('{http://schemas.openxmlformats.org/drawingml/2006/main}p')):
        body.remove(p)
    for it in items:
        if it[0] == 'eq':
            xml = _para(it[1], it[2], align)
        else:
            bold = len(it) > 2 and it[2]
            xml = _text_para(it[1], int((size - 4) * 100), '1F2A30' if bold else label_color, bold, align)
        body.append(etree.fromstring(xml))
    _size[0] = SZ
    return tb
