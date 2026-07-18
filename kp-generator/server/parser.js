const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

async function parseFile(filePath, mimetype) {
  const ext = filePath.split('.').pop().toLowerCase();

  if (mimetype === 'application/pdf' || ext === 'pdf') {
    const pdfParse = require('pdf-parse');
    const buffer = fs.readFileSync(filePath);
    const result = await pdfParse(buffer);
    return result.text;
  }

  if (
    mimetype === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
    mimetype === 'application/msword' ||
    mimetype === 'application/octet-stream' ||
    ext === 'docx' || ext === 'doc'
  ) {
    const mammoth = require('mammoth');
    const result = await mammoth.extractRawText({ path: filePath });
    return result.value;
  }

  throw new Error(`Неподдерживаемый тип файла: ${mimetype}`);
}

async function extractImages(filePath, sessionId) {
  const extractedDir = path.join(__dirname, '..', 'extracted', sessionId);
  fs.mkdirSync(extractedDir, { recursive: true });

  // Find pdfimages binary (Homebrew on Apple Silicon or Intel)
  const candidates = [
    'pdfimages',
    '/opt/homebrew/bin/pdfimages',
    '/usr/local/bin/pdfimages',
  ];
  let pdfimagesBin = null;
  for (const c of candidates) {
    try { execSync(`${c} -v`, { stdio: 'pipe' }); pdfimagesBin = c; break; } catch { /* try next */ }
  }

  if (!pdfimagesBin) {
    console.log('[parser] pdfimages недоступен, пропускаю извлечение изображений');
    return [];
  }

  try {
    const prefix = path.join(extractedDir, 'img');
    execSync(`"${pdfimagesBin}" -png "${filePath}" "${prefix}"`, { stdio: 'pipe', timeout: 30000 });
  } catch (err) {
    console.log('[parser] Ошибка извлечения изображений:', err.message);
    return [];
  }

  const allFiles = fs.readdirSync(extractedDir)
    .filter(f => /\.(png|jpg|jpeg|ppm|pbm)$/i.test(f))
    .sort();

  // Filter out icons, logos, banners
  const validFiles = [];
  for (const filename of allFiles) {
    try {
      const sizeOf = require('image-size');
      const dims = sizeOf(path.join(extractedDir, filename));
      const { width, height } = dims;
      const ratio = width / height;

      // Skip tiny images (icons)
      if (width < 200 || height < 150) continue;
      // Skip very wide banners/logos (ratio > 3.5 = typical header logo)
      if (ratio > 3.5) continue;
      // Skip very tall narrow images (decorative elements)
      if (ratio < 0.25) continue;

      validFiles.push(filename);
    } catch {
      validFiles.push(filename);
    }
  }

  console.log(`[parser] Извлечено изображений: ${validFiles.length}`);
  return validFiles;
}

function cleanupSession(sessionId) {
  const dir = path.join(__dirname, '..', 'extracted', sessionId);
  if (fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

module.exports = { parseFile, extractImages, cleanupSession };
