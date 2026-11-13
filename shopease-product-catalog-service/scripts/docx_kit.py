"""Small formatting helpers for scripts/build_word_documents.py (python-docx).

python-docx is a documentation tool only, not a dependency of the service, so it is not in
requirements.txt. Install it wherever the generator runs: pip install python-docx
"""

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

NAVY = RGBColor(0x1F, 0x3A, 0x5F)
GREY = RGBColor(0x59, 0x59, 0x59)
FILLS = {  # status word at the start of a cell -> background colour
    "PASS": "E2F0D9", "Passed": "E2F0D9", "Completed": "E2F0D9", "Complete": "E2F0D9", "Done": "E2F0D9", "Yes": "E2F0D9",
    "Blocked": "FCE4D6", "Partly": "FFF2CC", "Pending": "DDEBF7", "FAIL": "F8CBAD", "Failed": "F8CBAD", "No": "F8CBAD",
}
PROJECT = "ShopEase Product Catalog Service"


def _shade(element, fill: str) -> None:
    props = element.get_or_add_tcPr() if element.tag == qn("w:tc") else element.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    props.append(shd)


def _field(paragraph, instruction: str) -> None:
    run = paragraph.add_run()
    for kind, text in (("begin", None), (None, instruction), ("separate", None), (None, "1"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        elif text == "1":
            el = OxmlElement("w:t")
            el.text = text
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


class Doc:
    def __init__(self, title: str, subtitle: str, meta: list[tuple[str, str]]):
        self.doc = Document()
        self.title = title
        section = self.doc.sections[0]
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)  # A4
        section.orientation = WD_ORIENT.PORTRAIT
        for side in ("left_margin", "right_margin"):
            setattr(section, side, Cm(2.0))
        section.top_margin, section.bottom_margin = Cm(2.0), Cm(2.0)
        self._styles()
        self._header_footer()
        p = self.doc.add_paragraph(style="Title")
        p.add_run(title)
        p = self.doc.add_paragraph(style="Subtitle")
        p.add_run(subtitle)
        self.table(["Item", "Detail"], [list(m) for m in meta], widths=[4.5, 12.5])
        self.doc.core_properties.title = title
        self.doc.core_properties.subject = PROJECT
        self.doc.core_properties.author = ""

    def _styles(self) -> None:
        styles = self.doc.styles
        normal = styles["Normal"]
        normal.font.name, normal.font.size = "Calibri", Pt(10.5)
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
        normal.paragraph_format.space_after = Pt(6)
        normal.paragraph_format.line_spacing = 1.1
        for name, size, before, after in (("Title", 24, 0, 4), ("Subtitle", 13, 0, 12), ("Heading 1", 15, 16, 6),
                                          ("Heading 2", 12.5, 12, 4), ("Heading 3", 11, 10, 3)):
            st = styles[name]
            st.font.name, st.font.size, st.font.color.rgb = "Calibri", Pt(size), NAVY if name != "Subtitle" else GREY
            st.font.bold = name != "Subtitle"
            rfonts = st.element.rPr.find(qn("w:rFonts"))
            for attr in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
                if rfonts is not None and rfonts.get(qn(attr)) is not None:
                    del rfonts.attrib[qn(attr)]
            st.paragraph_format.space_before, st.paragraph_format.space_after = Pt(before), Pt(after)
            st.paragraph_format.keep_with_next = True

    def _header_footer(self) -> None:
        section = self.doc.sections[0]
        head = section.header.paragraphs[0]
        head.text = f"{PROJECT}  |  {self.title}"
        head.runs[0].font.size, head.runs[0].font.color.rgb = Pt(8.5), GREY
        foot = section.footer.paragraphs[0]
        foot.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = foot.add_run("Page ")
        run.font.size = Pt(8.5)
        _field(foot, "PAGE")
        foot.add_run(" of ").font.size = Pt(8.5)
        _field(foot, "NUMPAGES")

    # --- content -------------------------------------------------------------------------------
    def h1(self, text: str) -> None:
        self.doc.add_heading(text, level=1)

    def h2(self, text: str) -> None:
        self.doc.add_heading(text, level=2)

    def h3(self, text: str) -> None:
        self.doc.add_heading(text, level=3)

    def p(self, text: str, *, bold_prefix: str | None = None, italic: bool = False) -> None:
        para = self.doc.add_paragraph()
        if bold_prefix:
            para.add_run(bold_prefix).bold = True
        self._inline(para, text, italic=italic)

    def _inline(self, para, text: str, italic: bool = False) -> None:
        """`code` spans in Consolas; **bold** spans in bold."""
        import re
        for part in re.split(r"(`[^`]+`|\*\*[^*]+\*\*)", text):
            if not part:
                continue
            if part.startswith("`"):
                run = para.add_run(part[1:-1])
                run.font.name = "Consolas"
                run.font.size = Pt(9.5)
                run.font.color.rgb = RGBColor(0x8B, 0x1A, 0x1A)
            elif part.startswith("**"):
                run = para.add_run(part[2:-2])
                run.bold = True
            else:
                run = para.add_run(part)
            run.italic = italic

    def bullets(self, items: list[str], style: str = "List Bullet") -> None:
        for item in items:
            para = self.doc.add_paragraph(style=style)
            para.paragraph_format.space_after = Pt(2)
            if item.startswith("**") and "**" in item[2:]:
                end = item.index("**", 2)
                para.add_run(item[2:end]).bold = True
                self._inline(para, item[end + 2:])
            else:
                self._inline(para, item)

    def numbered(self, items: list[str]) -> None:
        self.bullets(items, style="List Number")

    def code(self, text: str) -> None:
        para = self.doc.add_paragraph()
        para.paragraph_format.space_after = Pt(8)
        para.paragraph_format.line_spacing = 1.0
        _shade(para._p, "F2F2F2")
        lines = text.rstrip("\n").split("\n")
        for i, line in enumerate(lines):
            run = para.add_run(line)
            run.font.name, run.font.size = "Consolas", Pt(8.5)
            run._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:hAnsi"), "Consolas")
            if i < len(lines) - 1:
                run.add_break()

    def note(self, text: str) -> None:
        para = self.doc.add_paragraph()
        _shade(para._p, "FFF2CC")
        para.add_run("Note: ").bold = True
        self._inline(para, text)

    def table(self, headers: list[str], rows: list[list[str]], widths: list[float] | None = None,
              status_col: int | None = None) -> None:
        t = self.doc.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        t.autofit = False
        for i, h in enumerate(headers):
            cell = t.rows[0].cells[i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(h)
            run.bold, run.font.size, run.font.color.rgb = True, Pt(9.5), RGBColor(0xFF, 0xFF, 0xFF)
            _shade(cell._tc, "1F3A5F")
        self._repeat_header(t.rows[0])
        for row in rows:
            cells = t.add_row().cells
            for i, value in enumerate(row):
                cells[i].text = ""
                para = cells[i].paragraphs[0]
                para.paragraph_format.space_after = Pt(0)
                self._inline(para, str(value))
                for run in para.runs:
                    run.font.size = Pt(9) if run.font.name != "Consolas" else Pt(8.5)
                cols = [status_col] if status_col is not None else []
                if i in cols:
                    for word, fill in FILLS.items():
                        if str(value).startswith(word):
                            _shade(cells[i]._tc, fill)
                            break
        if widths:
            for row in t.rows:
                for i, w in enumerate(widths):
                    row.cells[i].width = Cm(w)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    @staticmethod
    def _repeat_header(row) -> None:
        tr_pr = row._tr.get_or_add_trPr()
        el = OxmlElement("w:tblHeader")
        el.set(qn("w:val"), "true")
        tr_pr.append(el)

    def page_break(self) -> None:
        self.doc.add_page_break()

    def save(self, path) -> None:
        self.doc.save(str(path))
