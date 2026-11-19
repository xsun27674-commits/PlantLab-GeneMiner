from io import BytesIO

from zipfile import ZipFile
from docx.shared import Cm
from PIL import Image

from src import brand
from src.report import word_report


def test_wide_logo_on_cover_and_square_favicon(tmp_path, monkeypatch):
    monkeypatch.setattr(brand, "ASSETS", tmp_path)
    monkeypatch.delenv("GENEMINER_LOGO_PATH", raising=False)
    monkeypatch.delenv("GENEMINER_LOGO_ICON_PATH", raising=False)
    banner = tmp_path / "logo.png"
    Image.new("RGB", (1536, 1024)).save(banner)
    assert brand.logo() == banner
    assert brand.logo_icon() is None

    cover = word_report("Test", "", "", {"软件版本": "3.0.0", "科研信息": {}}, {}, {}, [])
    with ZipFile(BytesIO(cover)) as package:
        header = package.read("word/header1.xml")
        assert f'cx="{int(Cm(1))}"'.encode() in header
        assert b"<w:drawing>" not in package.read("word/document.xml")
    icon = tmp_path / "logo-icon.png"
    Image.new("RGB", (64, 64)).save(icon)
    assert brand.logo_icon() == icon

    banner.write_bytes(b"invalid PNG")
    assert brand.logo() is None
