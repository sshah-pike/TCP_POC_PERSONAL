# Rule pack v1 source extraction (S4 commit 1)

Dev-time spike. Never imported by `src/`. Needs PyMuPDF (`pymupdf`), which is a dev tool only and not a shipped
dependency.

| Script | What it does |
| --- | --- |
| `survey.py` | Text-layer survey of the four source PDFs: sha256, page count, low-text pages |
| `extract.py` | Writes `tests/fixtures/rule_pack_sources/cited_pages.json`, the normalised text of every MUTCD page the pack cites; `--check` re-extracts and compares |

Rules come from the MUTCD only. The three reference TMP drafts are comparison material, not rule sources: the survey
checks their text layer, but they are not snapshotted.

Tests check every rule-pack quote against the snapshot, so they need neither PyMuPDF nor the PDFs.

## Survey result (2026-10-29, PyMuPDF 1.28.2)

| Document | sha256 | Pages | Text layer |
| --- | --- | --- | --- |
| `docs/sources/CHAPTER 6 - DEC 2023 MUTCD REVISION.pdf` | `16e03bf4c1a731c5e13a8c8c60a49231a12918f151655564859e341755c0dbf0` | 204 (printed 765 to 968) | Yes. 8 pages under 200 characters, all figure-only or blank (PDF 8, 13, 20, 28, 89, 99, 111, 204); none is cited |
| `docs/references/WPI 3168057 - 130 COLORADO ST - MATTAPAN - TMP.pdf` | `cd8c42784235072ea0f84b580af07c49e31b419c3838a9460194c87b043a200b` | 1 | Yes, every sheet |
| `docs/references/1A8J1KB WPI 3171586, E Second St, South Boston, MA - TMP.pdf` | `352af820c2949ca10f974336a931b3a6e04e9471d5ea6a9aa2f654afc89e0f88` | 2 | Yes, every sheet |
| `docs/references/1A8L6XS WPI 3178233 - 125-165 GRANITE ST (US-1), WESTERLY, RI - TMP.pdf` | `b1dc4ec827a796daebabad7ba381d6fcef5061ceddeb9affe640c9803e3604ae` | 6 | Yes, every sheet |

Printed MUTCD page = PDF page + 764 on every cited page; the snapshot stores both, read from the page footer.

## Limit: figure drawings

On the four figure pages (PDF 97, 107, 115, 161 = printed 861, 871, 879, 925) only the title and the "Notes: See
Table ..." text are in the text layer. Every label in the drawing (sign codes, A/B/C, "1/3 L", "10 ft MIN.",
"50 to 100 ft", "500 ft", "100 ft (optional)", "Buffer space (optional)") is vector outlines. Values read only from a
drawing cannot be checked by quote; they were read from page renders (`pymupdf` `get_pixmap(dpi=110)`).
