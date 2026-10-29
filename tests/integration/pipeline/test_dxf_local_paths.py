"""S3 (Q17-B): a DXF/DWG written by the DWT renderer holds no local path. The real check needs the ODA File Converter and
is skipped without it (the owner runs one real render later); the scan itself is always tested."""
import json, os

import pytest

from tcp_planner.orchestration.pipeline import DWT_CONFIG_PATH, main
from tests.support.localpaths import dxf_header, local_path_hits

CLEAN_DXF = b"0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1027\n9\n$INSUNITS\n70\n6\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n"


def test_the_scan_finds_paths_and_passes_a_clean_header(tmp_path):
    assert local_path_hits(dxf_header(CLEAN_DXF), extra=[tmp_path]) == []
    dirty = CLEAN_DXF.replace(b"AC1027", b"AC1027\n9\n$DWGNAME\n1\nC:\\Users\\someone\\work\\plan.dxf")
    assert any("C:\\" in h for h in local_path_hits(dxf_header(dirty)))
    assert local_path_hits(b"x /home/someone/plan.dxf y") == ["/home/someone"]
    assert local_path_hits(f"x {tmp_path} y".encode(), extra=[tmp_path]) != []
    assert local_path_hits(b"..\x01\x02 a:/ b ..", generic=False) == []        # binary: no generic patterns
    assert local_path_hits(b"..\x01\x02 a:/ b ..") == ["a:/"]
    assert str(tmp_path).replace("\\", "/") in local_path_hits(f"x {str(tmp_path).replace(chr(92), '/')} y".encode(), extra=[tmp_path])
    assert dxf_header(b"binary DWG bytes") == b"binary DWG bytes"
    assert dxf_header(CLEAN_DXF).startswith(b"SECTION") and b"ENTITIES" not in dxf_header(CLEAN_DXF)    # only the header


def _converter_installed():
    import ezdxf
    from ezdxf.addons import odafc
    with open(DWT_CONFIG_PATH, encoding="utf-8") as f: cfg = json.load(f)
    exe = os.environ.get("TCP_ODA_FILE_CONVERTER") or cfg.get("oda_file_converter")
    if exe: ezdxf.options.set("odafc-addon", "win_exec_path", exe)
    return odafc.is_installed()


def test_a_rendered_dxf_and_dwg_hold_no_local_path(tmp_path, monkeypatch):
    if not _converter_installed(): pytest.skip("ODA File Converter not installed: no DXF/DWG is rendered on this machine")
    monkeypatch.setenv("TCP_RENDER_SHEET", "0")
    out = tmp_path / "local_marker_folder" / "out"
    main(["--offline", "supported", "--out", str(out)])
    files = [out / n for n in ("plan.dxf", "plan.dwg") if (out / n).is_file()]
    if not files: pytest.skip("the DWT renderer produced no DXF/DWG here (template or blocks missing: it fails closed)")
    for f in files:
        data = f.read_bytes()
        scanned = dxf_header(data) if f.suffix == ".dxf" else data
        assert local_path_hits(scanned, extra=[out, tmp_path, "local_marker_folder"], generic=f.suffix == ".dxf") == [], f.name
