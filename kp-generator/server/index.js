require('dotenv').config();
const express = require('express');
const multer  = require('multer');
const path    = require('path');
const fs      = require('fs');
const { v4: uuidv4 } = require('uuid');

const { parseFile } = require('./parser');
const { extractKPData } = require('./ai');
const { generateKP }               = require('./generator');

const app  = express();
const PORT = process.env.PORT || 3000;

const UPLOADS_DIR   = path.join(__dirname, '..', 'uploads');
const OUTPUT_DIR    = path.join(__dirname, '..', 'output');
const EXTRACTED_DIR = path.join(__dirname, '..', 'extracted');

[UPLOADS_DIR, OUTPUT_DIR, EXTRACTED_DIR].forEach(d => fs.mkdirSync(d, { recursive: true }));

app.use(express.json({ limit: '20mb' }));
app.use(express.static(path.join(__dirname, '..', 'client')));

const storage = multer.diskStorage({
  destination: UPLOADS_DIR,
  filename: (req, file, cb) => cb(null, `${uuidv4()}-${file.originalname}`),
});
const upload = multer({
  storage,
  limits: { fileSize: 30 * 1024 * 1024 },
  fileFilter: (req, file, cb) => {
    const ok = /\.(pdf|docx|doc)$/i.test(file.originalname);
    cb(ok ? null : new Error('Поддерживаются только PDF и DOCX'), ok);
  },
});

const photoStorage = multer.diskStorage({
  destination: UPLOADS_DIR,
  filename: (req, file, cb) => {
    const ext = path.extname(file.originalname).toLowerCase() || '.jpg';
    cb(null, `photo_${uuidv4()}${ext}`);
  },
});
const uploadPhoto = multer({
  storage: photoStorage,
  limits: { fileSize: 20 * 1024 * 1024 },
  fileFilter: (req, file, cb) => {
    const ok = file.mimetype.startsWith('image/');
    cb(ok ? null : new Error('Только изображения'), ok);
  },
});

/* ─── POST /api/extract ─── */
app.post('/api/extract', upload.single('file'), async (req, res) => {
  const sessionId = uuidv4();
  let filePath = null;
  try {
    let text = '';

    if (req.file) {
      filePath = req.file.path;
      text = await parseFile(req.file.path, req.file.mimetype);
    } else if (req.body.text) {
      text = req.body.text;
    } else {
      return res.status(400).json({ success: false, error: 'Необходимо загрузить файл или вставить текст' });
    }

    if (!text || text.trim().length < 10) {
      return res.status(400).json({ success: false, error: 'Не удалось извлечь текст из файла' });
    }

    const extracted = await extractKPData(text);

    res.json({
      success: true,
      data: {
        name:         extracted.name         || '',
        brand:        extracted.brand        || '',
        warranty:     extracted.warranty     || '',
        availability: extracted.availability || '',
        price:        extracted.price        || '',
        paymentTerms: Array.isArray(extracted.paymentTerms) ? extracted.paymentTerms : [],
        blocks:       extracted.blocks       || [],
        sessionId,
      },
    });
  } catch (err) {
    console.error('Extract error:', err);
    res.status(500).json({ success: false, error: err.message || 'Ошибка при извлечении данных' });
  } finally {
    if (filePath && fs.existsSync(filePath)) fs.unlinkSync(filePath);
  }
});

/* ─── POST /api/upload-photo ─── */
app.post('/api/upload-photo', uploadPhoto.single('photo'), async (req, res) => {
  try {
    let sessionId = req.body.sessionId;
    if (!sessionId || !/^[a-f0-9-]{36}$/.test(sessionId)) sessionId = uuidv4();
    if (!req.file) return res.status(400).json({ success: false, error: 'Нет файла' });

    const extractedDir = path.join(EXTRACTED_DIR, sessionId);
    fs.mkdirSync(extractedDir, { recursive: true });

    const ext = path.extname(req.file.originalname).toLowerCase() || '.jpg';
    const filename = `user_${uuidv4()}${ext}`;
    fs.renameSync(req.file.path, path.join(extractedDir, filename));

    res.json({ success: true, sessionId, filename });
  } catch (err) {
    console.error('Upload photo error:', err);
    res.status(500).json({ success: false, error: err.message });
  }
});

/* ─── GET /api/image/:sessionId/:filename ─── */
app.get('/api/image/:sessionId/:filename', (req, res) => {
  const { sessionId, filename } = req.params;
  if (!/^[a-f0-9-]{36}$/.test(sessionId)) return res.status(400).end();
  if (!/^[\w.-]+\.(png|jpg|jpeg|ppm)$/i.test(filename)) return res.status(400).end();

  const imgPath = path.join(EXTRACTED_DIR, sessionId, filename);
  if (!fs.existsSync(imgPath)) return res.status(404).end();
  res.sendFile(imgPath);
});

/* ─── POST /api/generate ─── */
app.post('/api/generate', async (req, res) => {
  try {
    const { kpData, clientName } = req.body;
    if (!kpData) return res.status(400).json({ success: false, error: 'Нет данных' });
    if (clientName) kpData.clientName = clientName;

    const fileId    = uuidv4();
    const outputPath = path.join(OUTPUT_DIR, `${fileId}.pptx`);

    await generateKP(kpData, outputPath);

    res.json({ success: true, fileId });
  } catch (err) {
    console.error('Generate error:', err);
    res.status(500).json({ success: false, error: err.message || 'Ошибка при генерации' });
  }
});

/* ─── GET /api/download/:fileId ─── */
app.get('/api/download/:fileId', (req, res) => {
  const { fileId } = req.params;
  if (!/^[a-f0-9-]{36}$/.test(fileId)) return res.status(400).end();

  const filePath = path.join(OUTPUT_DIR, `${fileId}.pptx`);
  if (!fs.existsSync(filePath)) return res.status(404).json({ error: 'Файл не найден' });

  res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.presentationml.presentation');
  res.setHeader('Content-Disposition', 'attachment; filename="KP_Remtechnika.pptx"');

  const stream = fs.createReadStream(filePath);
  stream.pipe(res);
  stream.on('close', () => {
    setTimeout(() => {
      try { fs.unlinkSync(filePath); } catch { /* ignore */ }
    }, 5000);
  });
});

app.listen(PORT, () => {
  console.log(`\n✅ Сервер запущен: http://localhost:${PORT}\n`);
});
