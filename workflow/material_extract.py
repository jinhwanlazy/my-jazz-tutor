"""Bounded PDF extraction in a disposable process (PDFium is not thread safe).

The parent supplies a cached local PDF, never an arbitrary URL or model command.
Only explicitly requested pages become images. No OCR result is called verified.
"""
import json
from pathlib import Path
import sys


def extract(source, output, pages):
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(source)
    try:
        if not 1 <= len(document) <= 300:
            raise ValueError('PDF must contain 1–300 pages.')
        chunks, remaining = [], 1_500_000
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            text = textpage.get_text_bounded().replace('\r\n', '\n')
            textpage.close()
            bounded = text[:min(14000, remaining)]
            remaining -= len(bounded)
            chunks.append({'locator': {'kind': 'pdf_page', 'page': index + 1,
                                       'label': f'PDF page {index + 1}'},
                           'text': bounded, 'truncated': len(bounded) < len(text)})
            if index + 1 in pages:
                width, height = page.get_size()
                if min(width, height) <= 0:
                    raise ValueError('Invalid page dimensions.')
                bitmap = page.render(scale=min(2, 1500 / max(width, height)))
                image = bitmap.to_pil()
                image.save(output.parent / f'page-{index + 1}.png')
                image.close()
                bitmap.close()
            page.close()
        output.write_text(json.dumps({'extractor': 'pdfium-text-1', 'page_count': len(document),
                                      'chunks': chunks}, ensure_ascii=False))
    finally:
        document.close()


if __name__ == '__main__':
    extract(sys.argv[1], Path(sys.argv[2]), json.loads(sys.argv[3]))
