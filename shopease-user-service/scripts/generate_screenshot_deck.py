"""Build DELIVERABELS/User_Service_Evidence_Screenshots.pptx from DELIVERABELS/screenshots/.

One slide per screenshot, each with a one-line heading, after a title slide. The images are placed
unchanged and scaled to fit; only 06 (a full-page capture) is cropped in PowerPoint to its endpoint
list. Requires python-pptx and Pillow.

    python scripts/generate_screenshot_deck.py
"""
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent / "DELIVERABELS"
SHOTS = ROOT / "screenshots"
OUT = ROOT / "User_Service_Evidence_Screenshots.pptx"

NAVY = RGBColor(0x1F, 0x3A, 0x5F)
INK = RGBColor(0x1E, 0x29, 0x3B)
MUTED = RGBColor(0x5B, 0x6B, 0x80)
FRAME = RGBColor(0xC8, 0xD1, 0xDC)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ICE = RGBColor(0xCA, 0xDC, 0xFC)

# (file, one-line heading, fraction of the image height to show)
SLIDES = [
    ("01_project_structure.png", "Project folder structure", 1),
    ("01b_project_structure_app_tests.png", "Application and test modules (app/ and tests/)", 1),
    ("02_docker_containers.png", "Docker containers running and healthy", 1),
    ("03_migration_log.png", "Alembic migrations run on container start", 1),
    ("04_mysql_tables.png", "MySQL tables: user_profiles and user_addresses", 1),
    ("05_health_endpoints.png", "Health checks: service up and database connected", 1),
    ("06_swagger_ui.png", "Swagger UI: all User Service endpoints", 0.55),
    ("07_auth_login_token.png", "Login on the Authentication Service (token redacted)", 1),
    ("08_authorize_with_token.png", "Swagger UI authorized with the JWT access token", 1),
    ("09_create_profile.png", "Create profile: POST /api/users/profile (201)", 1),
    ("10_get_profile.png", "Get profile: GET /api/users/profile (200)", 1),
    ("11_update_profile.png", "Update profile: PATCH /api/users/profile (200)", 1),
    ("12_create_address.png", "Create address: POST /api/users/addresses (201)", 1),
    ("13_list_addresses.png", "List addresses: GET /api/users/addresses (200)", 1),
    ("14_update_address.png", "Update address: PUT /api/users/addresses/{id} (200)", 1),
    ("15_set_default_address.png", "Set default address: PATCH /addresses/{id}/default (200)", 1),
    ("16_delete_address.png", "Delete address: DELETE /api/users/addresses/{id} (200)", 1),
    ("17_unauthorized_401.png", "Request without a token is rejected (401)", 1),
    ("18a_deactivate_account.png", "Deactivate account: PATCH /api/users/account/deactivate (200)", 1),
    ("18_forbidden_403.png", "Deactivated profile is blocked (403)", 1),
    ("19_mysql_data.png", "MySQL data: profiles and addresses", 1),
    ("20_pytest_results.png", "Automated tests: 518 passed (pytest)", 1),
    ("21_cross_user_access_denied.png", "Cross-user read blocked: user B cannot see A's address (404)", 1),
    ("21b_cross_user_delete_denied.png", "Cross-user delete blocked: user B cannot delete A's address (404)", 1),
    ("21c_owner_still_has_address.png", "Owner A still has the address, unchanged (200)", 1),
]

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.5)
IMAGE_TOP, IMAGE_BOTTOM = Inches(1.2), Inches(7.1)


def text(slide, value, left, top, width, height, size, color, bold=False, align=PP_ALIGN.LEFT):
    box = slide.shapes.add_textbox(left, top, width, height)
    frame = box.text_frame
    frame.word_wrap = False
    frame.margin_left = frame.margin_right = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = frame.paragraphs[0]
    paragraph.alignment = align
    run = paragraph.add_run()
    run.text = value
    run.font.name = "Calibri"
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return box


def background(slide, color):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def main():
    missing = [name for name, _, _ in SLIDES if not (SHOTS / name).exists()]
    extra = sorted({p.name for p in SHOTS.glob("*.png")} - {name for name, _, _ in SLIDES})
    if missing or extra:
        raise SystemExit(f"screenshots missing: {missing}; not in the deck: {extra}")

    deck = Presentation()
    deck.slide_width, deck.slide_height = SLIDE_W, SLIDE_H
    blank = deck.slide_layouts[6]

    title = deck.slides.add_slide(blank)
    background(title, NAVY)
    text(title, "ShopEase User Service", MARGIN, Inches(2.4), SLIDE_W - 2 * MARGIN, Inches(1), 44, WHITE, True)
    text(title, "Live evidence screenshots", MARGIN, Inches(3.4), SLIDE_W - 2 * MARGIN, Inches(0.7), 28, ICE)
    text(title, f"Captured from the running system on 11 November 2026  ·  {len(SLIDES)} screenshots  ·  "
                "tokens and passwords redacted", MARGIN, Inches(4.4), SLIDE_W - 2 * MARGIN, Inches(0.5), 16, ICE)

    for number, (name, heading, shown) in enumerate(SLIDES, start=1):
        slide = deck.slides.add_slide(blank)
        background(slide, WHITE)
        text(slide, heading, MARGIN, Inches(0.35), SLIDE_W - 2 * MARGIN - Inches(0.8), Inches(0.6), 28, INK, True)
        text(slide, str(number), SLIDE_W - MARGIN - Inches(0.6), Inches(0.35), Inches(0.6), Inches(0.6), 14, MUTED,
             align=PP_ALIGN.RIGHT)

        with Image.open(SHOTS / name) as image:
            width_px, height_px = image.size
        height_px *= shown
        box_w, box_h = SLIDE_W - 2 * MARGIN, IMAGE_BOTTOM - IMAGE_TOP
        scale = min(box_w / width_px, box_h / height_px)
        w, h = int(width_px * scale), int(height_px * scale)
        picture = slide.shapes.add_picture(str(SHOTS / name), Emu((SLIDE_W - w) // 2), Emu(IMAGE_TOP), Emu(w), Emu(h))
        picture.crop_bottom = 1 - shown
        picture.line.color.rgb = FRAME
        picture.line.width = Pt(0.75)
        picture.name = name

    deck.save(OUT)
    print(f"wrote {OUT.relative_to(ROOT.parent)}: {len(deck.slides)} slides")


if __name__ == "__main__":
    main()
