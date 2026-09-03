"""소스 텍스트 (명세 1절): UTF-8, BOM 제거, NFC 정규화, 줄 끝 정규화."""
import unicodedata
from .diagnostics import CompileError, Pos


def load_source(path):
    try:
        raw = open(path, "rb").read()
    except OSError as e:
        raise CompileError(Pos(path, 0, 0), f"파일을 열 수 없습니다: {e.strerror}")
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise CompileError(Pos(path, 0, 0), f"UTF-8이 아닙니다 (바이트 {e.start})")
    text = unicodedata.normalize("NFC", text)
    return text.replace("\r\n", "\n")
