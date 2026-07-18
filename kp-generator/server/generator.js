const PptxGenJS = require('pptxgenjs');
const fs = require('fs');
const path = require('path');

const C = {
  dark:      '2B2B2B',
  yellow:    'F5C400',
  white:     'FFFFFF',
  lightGray: 'F5F5F5',
  photoGray: 'DCDCDC',
  photoText: '999999',
  tableEven: 'F2F2F2',
  tableOdd:  'FAFAFA',
  trustBg:   'EEEEEE',
  trustText: '666666',
  border:    'E0E0E0',
  muted:     '777777',
};

const COMPANY = {
  name:    'ООО «Ремтехника»',
  inn:     'ИНН 2447007401',
  kpp:     'КПП 245401001',
  rs:      'Р/с 40702810231200000737',
};

const DEFAULT_TRUSTED =
  'АО «СУЭК», АК «АЛРОСА», ПАО «Русал», АО «Полюс», ГМК «Норильский никель», ' +
  'АО «Евраз», ПАО «НЛМК», АО «Металлоинвест», АО «Северсталь», АО «ММК»';

const W = 10, H = 5.625;

// Slide zones
const HDR_H  = 0.80;                       // header height
const NM_H   = 0.40;                       // machine name row height
const CON_Y  = HDR_H + NM_H + 0.04;       // content start Y  ≈ 1.24"
const CON_H  = H - CON_Y - 0.08;          // content height   ≈ 4.30"

/* ════════════════════════════════════════
   SHARED HELPERS
════════════════════════════════════════ */

/* White header with company info + yellow RT box + brand */
function addSlideHeader(pres, slide, brand) {
  // White background
  slide.addShape(pres.ShapeType.rect, {
    x: 0, y: 0, w: W, h: HDR_H,
    fill: { color: C.white }, line: { type: 'none' },
  });

  // Yellow RT box
  slide.addShape(pres.ShapeType.rect, {
    x: 0.14, y: 0.13, w: 0.54, h: 0.54,
    fill: { color: C.yellow }, line: { type: 'none' },
  });
  slide.addText('RT', {
    x: 0.14, y: 0.13, w: 0.54, h: 0.54,
    color: C.dark, fontSize: 17, bold: true, fontFace: 'Arial',
    align: 'center', valign: 'middle',
  });

  // Company name
  slide.addText(COMPANY.name, {
    x: 0.80, y: 0.10, w: 5.2, h: 0.24,
    color: C.dark, fontSize: 10, bold: true, fontFace: 'Arial', valign: 'middle',
  });
  // ИНН  КПП
  slide.addText(`${COMPANY.inn}  ${COMPANY.kpp}`, {
    x: 0.80, y: 0.34, w: 5.2, h: 0.20,
    color: C.muted, fontSize: 8, fontFace: 'Arial', valign: 'middle',
  });
  // Р/с
  slide.addText(COMPANY.rs, {
    x: 0.80, y: 0.54, w: 5.2, h: 0.20,
    color: C.muted, fontSize: 8, fontFace: 'Arial', valign: 'middle',
  });

  // Brand (right)
  if (brand) {
    slide.addText(brand, {
      x: 6.3, y: 0.13, w: 3.55, h: 0.54,
      color: C.dark, fontSize: 15, bold: true, fontFace: 'Arial',
      align: 'right', valign: 'middle',
    });
  }

  // Yellow separator line
  slide.addShape(pres.ShapeType.rect, {
    x: 0, y: HDR_H - 0.03, w: W, h: 0.03,
    fill: { color: C.yellow }, line: { type: 'none' },
  });
}

/* Machine name row shown on every non-cover slide */
function addMachineName(slide, name) {
  if (!name) return;
  slide.addText(name, {
    x: 0.2, y: HDR_H + 0.03, w: 9.6, h: NM_H - 0.03,
    color: C.dark, fontSize: 12, bold: true, fontFace: 'Arial', valign: 'middle',
  });
}

/* Gray photo placeholder */
function addPhotoPlaceholder(pres, slide, x, y, w, h) {
  slide.addShape(pres.ShapeType.rect, {
    x, y, w, h, fill: { color: C.photoGray }, line: { type: 'none' },
  });
  slide.addText('📷 Фото техники', {
    x, y, w, h, color: C.photoText, fontSize: 14, fontFace: 'Arial',
    align: 'center', valign: 'middle',
  });
}

/* ════════════════════════════════════════
   SLIDES
════════════════════════════════════════ */

/* ── Обложка (title) ── */
function buildTitleSlide(pres, block, brand, clientName) {
  const slide = pres.addSlide();

  // White bottom half
  slide.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: W, h: H, fill: { color: C.white }, line: { type: 'none' } });
  // Dark top half
  slide.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: W, h: H * 0.56, fill: { color: C.dark }, line: { type: 'none' } });
  // Yellow stripe
  slide.addShape(pres.ShapeType.rect, { x: 0, y: H * 0.56, w: W, h: 0.06, fill: { color: C.yellow }, line: { type: 'none' } });

  // RT logo top-left
  slide.addShape(pres.ShapeType.rect, { x: 0.3, y: 0.22, w: 0.50, h: 0.50, fill: { color: C.yellow }, line: { type: 'none' } });
  slide.addText('RT', { x: 0.3, y: 0.22, w: 0.50, h: 0.50, color: C.dark, fontSize: 16, bold: true, fontFace: 'Arial', align: 'center', valign: 'middle' });

  // РЕМТЕХНИКА
  slide.addText('РЕМТЕХНИКА', {
    x: 0.90, y: 0.22, w: 5, h: 0.50,
    color: C.yellow, fontSize: 20, bold: true, fontFace: 'Arial', valign: 'middle',
  });

  // Brand top-right
  if (brand) {
    slide.addText(brand, {
      x: 6, y: 0.22, w: 3.8, h: 0.50,
      color: C.white, fontSize: 15, fontFace: 'Arial', align: 'right', valign: 'middle',
    });
  }

  // "КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ"
  slide.addText('КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ', {
    x: 0.3, y: 1.05, w: 9.4, h: 0.36,
    color: C.yellow, fontSize: 11, fontFace: 'Arial', charSpacing: 2, valign: 'middle',
  });

  // Machine name
  slide.addText(block.title || '', {
    x: 0.3, y: 1.45, w: 9.4, h: 1.35,
    color: C.white, fontSize: 28, bold: true, fontFace: 'Arial', valign: 'middle', wrap: true,
  });

  // Specs line
  if (block.text) {
    slide.addText(block.text, {
      x: 0.3, y: 2.82, w: 9.4, h: 0.40,
      color: 'AAAAAA', fontSize: 11, fontFace: 'Arial', valign: 'middle', wrap: true,
    });
  }

  // Client
  if (clientName) {
    slide.addText('Подготовлено для:', {
      x: 0.3, y: H * 0.60, w: 3.5, h: 0.28,
      color: C.muted, fontSize: 9, fontFace: 'Arial', valign: 'middle',
    });
    slide.addText(clientName, {
      x: 0.3, y: H * 0.60 + 0.27, w: 6, h: 0.38,
      color: C.dark, fontSize: 15, bold: true, fontFace: 'Arial', valign: 'middle',
    });
  }

  // Yellow bottom bar
  slide.addShape(pres.ShapeType.rect, { x: 0, y: H - 0.18, w: W, h: 0.18, fill: { color: C.yellow }, line: { type: 'none' } });
}

/* ── Фото + Характеристики (split) — главный слайд ── */
function buildSplitSlide(pres, block, brand, machineName) {
  const slide = pres.addSlide();
  slide.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: W, h: H, fill: { color: C.white }, line: { type: 'none' } });
  addSlideHeader(pres, slide, brand);
  addMachineName(slide, machineName);

  const PHOTO_W = 5.20;
  const TABLE_X = PHOTO_W + 0.30;
  const TABLE_W = W - TABLE_X - 0.12;

  // Vertical separator line
  slide.addShape(pres.ShapeType.rect, {
    x: PHOTO_W + 0.14, y: CON_Y, w: 0.015, h: CON_H,
    fill: { color: C.border }, line: { type: 'none' },
  });

  // LEFT: Photo
  if (block.imagePath && fs.existsSync(block.imagePath)) {
    try {
      slide.addImage({
        path: block.imagePath,
        x: 0.14, y: CON_Y, w: PHOTO_W, h: CON_H,
        sizing: { type: 'contain', w: PHOTO_W, h: CON_H },
      });
    } catch {
      addPhotoPlaceholder(pres, slide, 0.14, CON_Y, PHOTO_W, CON_H);
    }
  } else {
    addPhotoPlaceholder(pres, slide, 0.14, CON_Y, PHOTO_W, CON_H);
  }

  // RIGHT: Rows with section headers
  // Row format: [param, value]  where value===null → section header
  const rows = (block.rows || []).filter(r => r[0] || r[1]);
  if (rows.length === 0) return;

  const sectionCount = rows.filter(r => r[1] === null).length;
  const dataCount    = rows.length - sectionCount;
  const SECTION_H    = 0.27;
  const DATA_H       = Math.min(0.265, (CON_H - sectionCount * SECTION_H) / Math.max(dataCount, 1));

  let curY     = CON_Y;
  let dataIdx  = 0;

  for (const row of rows) {
    if (curY + 0.1 > CON_Y + CON_H) break;

    const isSectionHeader = row[1] === null;

    if (isSectionHeader) {
      // Dark header row
      slide.addShape(pres.ShapeType.rect, {
        x: TABLE_X, y: curY, w: TABLE_W, h: SECTION_H,
        fill: { color: C.dark }, line: { type: 'none' },
      });
      slide.addText((row[0] || '').toUpperCase(), {
        x: TABLE_X + 0.08, y: curY, w: TABLE_W - 0.08, h: SECTION_H,
        color: C.yellow, fontSize: 8, bold: true, fontFace: 'Arial', valign: 'middle',
      });
      curY += SECTION_H;
    } else {
      const isSingleCol = !row[1] || row[1] === '';
      const rowBg = dataIdx % 2 === 0 ? C.tableEven : C.tableOdd;
      dataIdx++;

      slide.addShape(pres.ShapeType.rect, {
        x: TABLE_X, y: curY, w: TABLE_W, h: DATA_H,
        fill: { color: rowBg }, line: { type: 'none' },
      });

      if (isSingleCol) {
        slide.addText('• ' + (row[0] || ''), {
          x: TABLE_X + 0.08, y: curY, w: TABLE_W - 0.08, h: DATA_H,
          color: C.dark, fontSize: 9, fontFace: 'Arial', valign: 'middle',
        });
      } else {
        const pW = TABLE_W * 0.54;
        const vW = TABLE_W - pW;
        slide.addText(row[0] || '', {
          x: TABLE_X + 0.06, y: curY, w: pW - 0.06, h: DATA_H,
          color: C.muted, fontSize: 9, fontFace: 'Arial', valign: 'middle',
        });
        slide.addText(row[1] || '', {
          x: TABLE_X + pW, y: curY, w: vW - 0.06, h: DATA_H,
          color: C.dark, fontSize: 9, bold: true, fontFace: 'Arial', valign: 'middle',
        });
      }
      curY += DATA_H;
    }
  }
}

/* ── Таблица ── */
function buildTableSlide(pres, block, brand, machineName) {
  const slide = pres.addSlide();
  slide.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: W, h: H, fill: { color: C.white }, line: { type: 'none' } });
  addSlideHeader(pres, slide, brand);
  addMachineName(slide, machineName);

  slide.addText(block.title || '', {
    x: 0.2, y: CON_Y, w: 9.6, h: 0.34,
    color: C.dark, fontSize: 12, bold: true, fontFace: 'Arial', valign: 'middle',
  });

  const rows = (block.rows || []).filter(r => r[0] || r[1]);
  if (rows.length === 0) return;

  const singleCol = rows.every(r => !r[1] || r[1] === '');
  const colW = singleCol ? [9.6] : [5.2, 4.4];

  const TABLE_Y  = CON_Y + 0.38;
  const AVAIL_H  = H - TABLE_Y - 0.08;
  const MAX_ROWS = 14;
  const dataRowH = Math.min(0.285, (AVAIL_H - 0.30) / Math.min(rows.length, MAX_ROWS));
  const display  = rows.slice(0, Math.floor((AVAIL_H - 0.30) / dataRowH));

  const border = { type: 'none', pt: 0 };

  const headerCells = singleCol
    ? [{ text: 'НАИМЕНОВАНИЕ', options: { fontSize: 8, fontFace: 'Arial', bold: true, color: C.yellow, fill: { color: C.dark }, border } }]
    : [
        { text: 'НАИМЕНОВАНИЕ / ПАРАМЕТР', options: { fontSize: 8, fontFace: 'Arial', bold: true, color: C.yellow, fill: { color: C.dark }, border } },
        { text: 'ЗНАЧЕНИЕ',                options: { fontSize: 8, fontFace: 'Arial', bold: true, color: C.yellow, fill: { color: C.dark }, border } },
      ];

  const dataRows = display.map((row, i) => {
    const fill = { color: i % 2 === 0 ? C.tableEven : C.tableOdd };
    if (singleCol) {
      return [{ text: String(row[0] || ''), options: { fontSize: 10, fontFace: 'Arial', color: C.dark, fill, border } }];
    }
    return [
      { text: String(row[0] || ''), options: { fontSize: 10, fontFace: 'Arial', color: C.muted, fill, border } },
      { text: String(row[1] || ''), options: { fontSize: 10, fontFace: 'Arial', color: C.dark, bold: true, fill, border } },
    ];
  });

  slide.addTable([headerCells, ...dataRows], {
    x: 0.2, y: TABLE_Y, w: 9.6,
    rowH: [0.30, ...display.map(() => dataRowH)],
    colW,
  });
}

/* ── Фото ── */
function buildPhotoSlide(pres, block, brand, machineName) {
  const slide = pres.addSlide();
  slide.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: W, h: H, fill: { color: C.white }, line: { type: 'none' } });
  addSlideHeader(pres, slide, brand);
  addMachineName(slide, machineName);

  slide.addText(block.title || '', {
    x: 0.2, y: CON_Y, w: 9.6, h: 0.34,
    color: C.dark, fontSize: 12, bold: true, fontFace: 'Arial', valign: 'middle',
  });

  const imgY = CON_Y + 0.38;
  const imgH = H - imgY - 0.08;
  const imgPath = block.imagePath;

  if (imgPath && fs.existsSync(imgPath)) {
    try {
      slide.addImage({ path: imgPath, x: 0.5, y: imgY, w: 9, h: imgH,
        sizing: { type: 'contain', w: 9, h: imgH } });
      return;
    } catch { /* fallthrough */ }
  }
  addPhotoPlaceholder(pres, slide, 0.5, imgY, 9, imgH);
}

/* ── Текст ── */
function buildTextSlide(pres, block, brand, machineName) {
  const slide = pres.addSlide();
  slide.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: W, h: H, fill: { color: C.white }, line: { type: 'none' } });
  addSlideHeader(pres, slide, brand);
  addMachineName(slide, machineName);

  slide.addText(block.title || '', {
    x: 0.2, y: CON_Y, w: 9.6, h: 0.34,
    color: C.dark, fontSize: 12, bold: true, fontFace: 'Arial', valign: 'middle',
  });
  slide.addText(block.text || '', {
    x: 0.2, y: CON_Y + 0.38, w: 9.6, h: H - CON_Y - 0.46,
    color: C.dark, fontSize: 11, fontFace: 'Arial', valign: 'top', wrap: true,
  });
}

/* ── Цена и условия (всегда последний) ── */
function buildPriceSlide(pres, data, brand, machineName, manager, phone, trustedBy) {
  const slide = pres.addSlide();
  const { warranty, availability, price, paymentTerms } = data;

  slide.addShape(pres.ShapeType.rect, { x: 0, y: 0, w: W, h: H, fill: { color: C.white }, line: { type: 'none' } });
  addSlideHeader(pres, slide, brand);
  addMachineName(slide, machineName);

  // Three info boxes
  const BOX_Y = CON_Y;
  const BOX_H = 1.30;
  const GAP   = 0.15;
  const BOX_W = (W - GAP * 4) / 3;

  [
    { label: 'ГАРАНТИЯ',                value: warranty     || '—' },
    { label: 'НАЛИЧИЕ / СРОК ПОСТАВКИ', value: availability || '—' },
    { label: 'СТОИМОСТЬ',               value: price        || '—' },
  ].forEach((b, i) => {
    const bx = GAP + i * (BOX_W + GAP);
    slide.addShape(pres.ShapeType.rect, { x: bx, y: BOX_Y, w: BOX_W, h: BOX_H, fill: { color: C.lightGray }, line: { color: C.border, pt: 1 } });
    slide.addShape(pres.ShapeType.rect, { x: bx, y: BOX_Y, w: BOX_W, h: 0.06, fill: { color: C.yellow }, line: { type: 'none' } });
    slide.addText(b.label, { x: bx + 0.12, y: BOX_Y + 0.10, w: BOX_W - 0.24, h: 0.28, color: C.dark, fontSize: 8, bold: true, fontFace: 'Arial', valign: 'middle' });
    slide.addText(b.value, { x: bx + 0.12, y: BOX_Y + 0.40, w: BOX_W - 0.24, h: BOX_H - 0.50, color: C.dark, fontSize: 10, fontFace: 'Arial', valign: 'top', wrap: true });
  });

  const PAY_Y = BOX_Y + BOX_H + 0.14;
  const PAY_W = 6.3;

  // Payment terms
  slide.addShape(pres.ShapeType.rect, { x: GAP, y: PAY_Y, w: PAY_W, h: 0.25, fill: { color: C.dark }, line: { type: 'none' } });
  slide.addText('УСЛОВИЯ ОПЛАТЫ', { x: GAP + 0.10, y: PAY_Y, w: PAY_W, h: 0.25, color: C.yellow, fontSize: 8, bold: true, fontFace: 'Arial', valign: 'middle' });

  const payText = Array.isArray(paymentTerms) ? paymentTerms.join('\n') : String(paymentTerms || '');
  slide.addText(payText, { x: GAP, y: PAY_Y + 0.27, w: PAY_W, h: 0.68, color: C.dark, fontSize: 9, fontFace: 'Arial', valign: 'top', wrap: true });

  // Manager block (yellow box)
  const CX = GAP + PAY_W + GAP;
  const CW = W - CX - GAP;
  slide.addShape(pres.ShapeType.rect, { x: CX, y: PAY_Y, w: CW, h: 1.0, fill: { color: C.yellow }, line: { type: 'none' } });
  slide.addText('Ваш менеджер',  { x: CX, y: PAY_Y + 0.07, w: CW, h: 0.24, color: C.dark, fontSize: 8,  fontFace: 'Arial', align: 'center', valign: 'middle' });
  slide.addText(manager || '',   { x: CX, y: PAY_Y + 0.30, w: CW, h: 0.33, color: C.dark, fontSize: 12, bold: true, fontFace: 'Arial', align: 'center', valign: 'middle' });
  slide.addText(phone   || '',   { x: CX, y: PAY_Y + 0.63, w: CW, h: 0.30, color: C.dark, fontSize: 11, fontFace: 'Arial', align: 'center', valign: 'middle' });

  // "Нам доверяют"
  const TY = PAY_Y + 1.08;
  const TH = H - TY - 0.06;
  slide.addShape(pres.ShapeType.rect, { x: 0, y: TY, w: W, h: TH, fill: { color: C.trustBg }, line: { type: 'none' } });
  slide.addText('НАМ ДОВЕРЯЮТ:', { x: 0.2, y: TY + 0.05, w: 2.5, h: 0.24, color: C.dark, fontSize: 8, bold: true, fontFace: 'Arial', valign: 'middle' });
  slide.addText(trustedBy || DEFAULT_TRUSTED, { x: 0.2, y: TY + 0.30, w: 9.6, h: TH - 0.35, color: C.trustText, fontSize: 8, fontFace: 'Arial', valign: 'top', wrap: true });
}

/* ════════════════════════════════════════
   RESOLVE IMAGE PATH
════════════════════════════════════════ */
function resolveImagePath(block) {
  if (block.imageRef) {
    const { sessionId, filename } = block.imageRef;
    if (sessionId && filename) {
      const p = path.join(__dirname, '..', 'extracted', sessionId, filename);
      if (fs.existsSync(p)) return p;
    }
  }
  return null;
}

/* ════════════════════════════════════════
   MAIN
════════════════════════════════════════ */
async function generateKP(data, outputPath) {
  const pres = new PptxGenJS();
  const {
    name = '', brand = '', manager = '', phone = '', clientName = '',
    trustedBy = '', warranty = '', availability = '',
    price = '', paymentTerms = [], blocks = [],
  } = data;

  for (const block of blocks) {
    if (block.type === 'title') {
      buildTitleSlide(pres, block, brand, clientName);
    } else if (block.type === 'split') {
      buildSplitSlide(pres, { ...block, imagePath: resolveImagePath(block) }, brand, name);
    } else if (block.type === 'photo') {
      buildPhotoSlide(pres, { ...block, imagePath: resolveImagePath(block) }, brand, name);
    } else if (block.type === 'table') {
      buildTableSlide(pres, block, brand, name);
    } else if (block.type === 'text') {
      buildTextSlide(pres, block, brand, name);
    }
  }

  buildPriceSlide(pres, { warranty, availability, price, paymentTerms }, brand, name, manager, phone, trustedBy || DEFAULT_TRUSTED);

  await pres.writeFile({ fileName: outputPath });
}

module.exports = { generateKP, DEFAULT_TRUSTED };
